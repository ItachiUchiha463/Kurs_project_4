"""Конвеєр обробки метрик (ТЗ 3.1, кроки 4–7): значення → пороги → інциденти → стан об'єкта.

Це «серце» серверної частини: сюди потрапляє кожен пакет метрик після перевірки в services/ingest.py.

Порядок роботи для одного пакета (функція process, внизу файлу):
  1. З пакета лишається по одній найсвіжішій точці на ряд (метрика + instance).
  2. Для кожного ряду беремо поріг (services/thresholds.py), агрегуємо значення за вікно (_aggregate)
     і викликаємо чисту функцію engine/thresholds.step(): вона каже, чи відкрити/підвищити/знизити/закрити інцидент.
  3. _apply виконує ці рішення в БД: створює інцидент, пише події, придушує дочірні об'єкти.
  4. refresh_status перераховує статус об'єкта (ok / warning / critical / unavailable / unknown).
  5. Для нових і підвищених інцидентів викликається діагностика (services/diagnosis.py).
  6. У черзі сповіщень створюються записи (notify/outbox.py), а подія WebSocket чекає коміту (realtime/hub.py).

Усе це виконується в ОДНІЙ транзакції БД: або зберігається все (метрика, інцидент, діагноз, сповіщення), або нічого.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import AGENT_SILENT, AVAILABILITY_METRICS, SERVER_DOWN
from app.engine.thresholds import AGG_SQL, Deescalate, Escalate, Open, Resolve, State, Threshold, step
from app.models import Incident, Target
from app.repositories import incidents as repo
from app.notify import outbox
from app.realtime.hub import publish_after_commit
from app.services import diagnosis, events, thresholds

log = logging.getLogger("vigil.pipeline")

# Ключ ряду: (id об'єкта, назва метрики, instance). instance потрібен, бо в одного сервера може бути
# кілька дисків: ряд «disk_usage» для «/» і для «/data» оцінюється окремо.
Key = tuple[int, str, str]
# shortcut: стан «порушення триває з …» живе в пам'яті процесу; після перезапуску відлік duration_s
# починається заново, а відкриті інциденти відновлюються з БД. При кількох процесах – винести в таблицю.
_states: dict[Key, State] = {}


@dataclass
class Point:
    """Одна точка метрики з пакета агента (вже перевірена в ingest)."""
    metric: str
    instance: str
    ts: datetime
    value: float


@dataclass
class Change:
    """Що сталося з інцидентом на цьому кроці. Із Change потім будуються сповіщення й події WebSocket."""
    kind: str  # opened | escalated | deescalated | resolved
    incident: Incident
    target: Target
    value: float
    ts: datetime


async def _aggregate(db: AsyncSession, target_id: int, p: Point, th: Threshold) -> float:
    """Значення для порівняння з порогом: або сама точка (last), або агрегат за вікно (avg, max, delta).

    Так одинична точка-«викид» не відкриває інцидент: оцінюється, наприклад, середнє CPU за останні 2 хвилини.
    """
    if th.agg == "last" or th.window_s <= 0:
        return p.value
    # Агрегат рахує сама БД. AGG_SQL[th.agg] береться зі словника (не від користувача), тож f-рядок тут безпечний;
    # усі значення параметрів передаються окремо (:t, :n, …).
    row = await db.execute(text(
        f"SELECT {AGG_SQL[th.agg]} FROM metrics WHERE target_id = :t AND name = :n AND instance = :i AND ts > :s AND ts <= :e"),
        {"t": target_id, "n": p.metric, "i": p.instance, "s": p.ts - timedelta(seconds=th.window_s), "e": p.ts})
    value = row.scalar()  # None, лише якщо вікно порожнє
    return p.value if value is None else value


async def _state(db: AsyncSession, key: Key) -> State:
    """Стан ряду з пам'яті. Якщо процес щойно стартував, стан відновлюється з БД: чи є відкритий інцидент."""
    if key not in _states:
        live = await repo.get_live(db, *key)
        _states[key] = State(incident=live.severity) if live else State()
    return _states[key]


def keep_silent(incident: Incident) -> None:
    """Після ручного закриття оцінювач і далі вважає інцидент відкритим, але нового не створює.

    Поки значення погане, нічого не відбувається; коли воно нормалізується, стан скидається, і наступне порушення
    відкриє вже новий інцидент. Без цього ручне закриття за ще поганого значення одразу відкривало б дубль.
    shortcut: стан у пам'яті; після перезапуску процесу порушення, що триває, відкриє інцидент знову.
    """
    _states[(incident.target_id, incident.metric, incident.instance)] = State(incident=incident.severity)


def forget_target(target_id: int) -> None:
    """Забуває стани всіх рядів об'єкта (викликається при видаленні об'єкта, щоб не тримати зайве в пам'яті)."""
    for key in [k for k in _states if k[0] == target_id]:
        del _states[key]


async def _apply(db: AsyncSession, target: Target, key: Key, act, ts: datetime) -> list[Change]:
    """Виконує одну дію оцінювача в БД: Open / Escalate / Deescalate / Resolve. Повертає зміни для сповіщень."""
    if isinstance(act, Open):
        # --- Відкриття інциденту ---
        # ТЗ 7.1.1: поки сервер недоступний, порушення на його дочірніх об'єктах не відкривають звичайних інцидентів
        # (контейнер чи БД сервера, що «впав», – лише наслідок). Тоді інцидент одразу створюється придушеним.
        parent = await repo.server_down(db, target.host_id) if target.host_id and target.type != "server" else None
        inc = Incident(owner_id=target.owner_id, target_id=target.id, metric=key[1], instance=key[2],
                       severity=act.severity, status="suppressed" if parent else "open", suppressed_by=parent.id if parent else None,
                       value_at_open=act.value, first_breach_at=act.first_breach_at, started_at=ts)
        db.add(inc)
        await db.flush()  # flush, щоб отримати inc.id для подій нижче
        # Хронологія: спершу «виявлено» (коли почалося порушення), потім «відкрито» (коли минула тривалість).
        repo.add_event(db, inc.id, "detected", act.value, act.first_breach_at)
        repo.add_event(db, inc.id, "suppressed" if parent else "opened", act.value, ts)
        changes = [Change("suppressed" if parent else "opened", inc, target, act.value, ts)]
        if target.type == "server" and key[1] in SERVER_DOWN:
            # Сервер недоступний за ping: придушуємо вже відкриті інциденти його об'єктів і позначаємо їх недоступними.
            for child in await suppress_children(db, inc, ts):
                changes.append(Change("suppressed", child, await db.get(Target, child.target_id), child.value_at_open or 0.0, ts))
            await db.execute(update(Target).where(Target.host_id == target.id).values(status="unavailable"))  # «недоступний через сервер»
        return changes
    # --- Решта дій стосується вже відкритого інциденту ---
    inc = await repo.get_live(db, *key)
    if inc is None:  # інцидент закрили вручну, поки стан ще пам'ятав його
        return []
    quiet = inc.status == "suppressed"  # придушений інцидент змінює рівень і закривається без сповіщень
    if isinstance(act, Escalate):
        inc.severity = act.severity
        repo.add_event(db, inc.id, "escalated", act.value, ts)
        return [] if quiet else [Change("escalated", inc, target, act.value, ts)]
    if isinstance(act, Deescalate):
        inc.severity = act.severity
        repo.add_event(db, inc.id, "deescalated", act.value, ts)
        return [] if quiet else [Change("deescalated", inc, target, act.value, ts)]
    if isinstance(act, Resolve):
        inc.status, inc.resolved_at = "resolved", ts
        repo.add_event(db, inc.id, "resolved", act.value, ts, note="автоматично")
        changes = [Change("resolved", inc, target, act.value, ts)]
        if target.type == "server" and key[1] in SERVER_DOWN:
            # Сервер знову доступний: закриваємо придушені інциденти його об'єктів.
            changes += await release(db, target.id, ts)
        return changes
    return []


async def suppress_children(db: AsyncSession, parent: Incident, ts) -> list[Incident]:
    """Щойно сервер став недоступним: невідкриті дочірні інциденти (ще не підтверджені) стають придушеними.

    shortcut: сповіщення про дочірній інцидент, що вже встигло піти, не відкликається.
    """
    rows = list(await db.scalars(select(Incident).join(Target, Target.id == Incident.target_id).where(
        Target.host_id == parent.target_id, Incident.status == "open")))
    for inc in rows:
        inc.status, inc.suppressed_by = "suppressed", parent.id
        repo.add_event(db, inc.id, "suppressed", ts=ts, note="Сервер недоступний")
    return rows


async def _release_children(db: AsyncSession, server_id: int, ts) -> list[Incident]:
    """Сервер повернувся: придушені інциденти закриваються, а об'єкти оцінюються заново зі свіжих даних."""
    if await repo.server_down(db, server_id):
        return []
    rows = list(await db.scalars(select(Incident).join(Target, Target.id == Incident.target_id).where(
        Target.host_id == server_id, Incident.status == "suppressed")))
    for inc in rows:
        inc.status, inc.resolved_at = "resolved", ts
        repo.add_event(db, inc.id, "resolved", ts=ts, note="Сервер відновився")
    return rows


async def release(db: AsyncSession, server_id: int, ts: datetime) -> list[Change]:
    """Сервер знову доступний: придушені інциденти закрито, а дочірні об'єкти оцінюються заново (ТЗ 7.1.1)."""
    changes = []
    if not await repo.server_down(db, server_id):
        await db.execute(update(Target).where(Target.host_id == server_id, Target.status == "unavailable").values(status="unknown"))
    for child in await _release_children(db, server_id, ts):
        # Забуваємо стан цих рядів: наступна метрика оцінюватиметься з нуля, а не за застарілим станом.
        _states.pop((child.target_id, child.metric, child.instance), None)
        changes.append(Change("resolved", child, await db.get(Target, child.target_id), child.value_at_open or 0.0, ts))
    return changes


async def refresh_status(db: AsyncSession, target: Target, server_down: bool | None = None) -> None:
    """Перераховує статус об'єкта за його відкритими інцидентами (дашборд читає лише це поле, без складних запитів).

    Пріоритет від найвищого до найнижчого:
      unavailable – недоступний сам або через недоступний сервер;
      unknown     – лише агент мовчить, а ping збою не підтвердив (збій сервера й втрата зв'язку виглядають однаково);
      critical / warning – за найвищим рівнем відкритих інцидентів;
      ok          – відкритих інцидентів немає.

    server_down: відомо викликачеві (ingest перевіряє раз на пакет); None – запитати в БД.
    """
    live = await repo.live_for_target(db, target.id)
    if server_down is None:
        server_down = bool(target.host_id and target.type != "server" and await repo.server_down(db, target.host_id))
    if server_down or any(i.metric in AVAILABILITY_METRICS and i.metric != AGENT_SILENT for i in live):
        target.status = "unavailable"
    elif any(i.metric == AGENT_SILENT for i in live):  # агент мовчить, а ping збою не підтвердив: стан невідомий
        target.status = "unknown"
    elif any(i.severity == "critical" for i in live):
        target.status = "critical"
    elif live:
        target.status = "warning"
    else:
        target.status = "ok"


async def process(db: AsyncSession, target: Target, points: list[Point], server_down: bool | None = None) -> list[Change]:
    """Головна точка входу конвеєра: обробляє пакет точок одного об'єкта (див. опис кроків угорі файлу).

    points – лише свіжі записи; пізні з буфера агента сюди не потрапляють (ТЗ 5.1).
    Повертає список змін інцидентів (для тестів і журналу).
    """
    # Крок 1: з пакета беремо по одній найсвіжішій точці на ряд. Пакет міг містити кілька значень однієї метрики
    # (агент накопичував їх без зв'язку), але стан порогів оновлюється за найновішим.
    latest: dict[tuple[str, str], Point] = {}
    for p in sorted(points, key=lambda x: x.ts):
        latest[(p.metric, p.instance)] = p
    changes: list[Change] = []
    for (metric, instance), p in latest.items():
        # Крок 2: поріг для цієї метрики (з урахуванням власних налаштувань користувача).
        th = await thresholds.resolve(db, target, metric)
        if th is None:
            continue  # для метрики порога немає (наприклад, swap_usage): лише зберігаємо точки, інциденту не буде
        key = (target.id, metric, instance)
        state = await _state(db, key)
        value = await _aggregate(db, target.id, p, th)
        _states[key], actions = step(state, th, value, p.ts)  # чиста функція: нічого не пише в БД
        for act in actions:
            changes += await _apply(db, target, key, act, p.ts)  # крок 3: рішення -> БД
    # Крок 4: статус об'єкта для дашборда.
    await refresh_status(db, target, server_down)
    for c in changes:
        if c.kind in ("opened", "escalated"):
            # Крок 5: діагностика (причина, докази, контекст). Для знижень і закриттів вона не потрібна.
            await diagnosis.diagnose_incident(db, c.incident, target, c.ts)
        log.info("інцидент %s", c.kind, extra={"incident_id": c.incident.id, "target_id": c.target.id,
                                              "metric": c.incident.metric, "severity": c.incident.severity})
    # Крок 6а: записи для Telegram у тій самій транзакції (Transactional Outbox).
    await outbox.enqueue(db, changes)
    if latest:
        # Крок 6б: подія для браузера. Реально надсилається лише ПІСЛЯ коміту (publish_after_commit),
        # щоб клієнт не побачив того, чого після відкату транзакції не існуватиме.
        publish_after_commit(db, target.owner_id, events.metrics_event(
            target, {k: (p.ts, p.value) for k, p in latest.items()}))
    for c in changes:
        publish_after_commit(db, c.target.owner_id, events.incident_event(c.incident, c.target.name, c.kind))
    return changes
