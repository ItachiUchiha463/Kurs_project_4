"""Конвеєр обробки метрик (ТЗ 3.1, кроки 4–7): значення → пороги → інциденти → стан об'єкта."""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import AVAILABILITY_METRICS, SERVER_AVAILABILITY
from app.engine.thresholds import AGG_SQL, Deescalate, Escalate, Open, Resolve, State, Threshold, step
from app.models import Incident, Target
from app.repositories import incidents as repo
from app.notify import outbox
from app.realtime.hub import publish_after_commit
from app.services import diagnosis, events, thresholds

log = logging.getLogger("vigil.pipeline")

Key = tuple[int, str, str]  # (target_id, metric, instance)
# shortcut: стан «порушення триває з …» живе в пам'яті процесу; після перезапуску відлік duration_s
# починається заново, а відкриті інциденти відновлюються з БД. При кількох процесах – винести в таблицю.
_states: dict[Key, State] = {}


@dataclass
class Point:
    metric: str
    instance: str
    ts: datetime
    value: float


@dataclass
class Change:
    kind: str  # opened | escalated | deescalated | resolved
    incident: Incident
    target: Target
    value: float
    ts: datetime


async def _aggregate(db: AsyncSession, target_id: int, p: Point, th: Threshold) -> float:
    if th.agg == "last" or th.window_s <= 0:
        return p.value
    row = await db.execute(text(
        f"SELECT {AGG_SQL[th.agg]} FROM metrics WHERE target_id = :t AND name = :n AND instance = :i AND ts > :s AND ts <= :e"),
        {"t": target_id, "n": p.metric, "i": p.instance, "s": p.ts - timedelta(seconds=th.window_s), "e": p.ts})
    value = row.scalar()  # None, лише якщо вікно порожнє
    return p.value if value is None else value


async def _state(db: AsyncSession, key: Key) -> State:
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
    for key in [k for k in _states if k[0] == target_id]:
        del _states[key]


async def _apply(db: AsyncSession, target: Target, key: Key, act, ts: datetime) -> list[Change]:
    if isinstance(act, Open):
        # ТЗ 7.1.1: поки сервер недоступний, порушення на його дочірніх об'єктах не відкривають звичайних інцидентів
        parent = await repo.server_down(db, target.host_id) if target.host_id and target.type != "server" else None
        inc = Incident(owner_id=target.owner_id, target_id=target.id, metric=key[1], instance=key[2],
                       severity=act.severity, status="suppressed" if parent else "open", suppressed_by=parent.id if parent else None,
                       value_at_open=act.value, first_breach_at=act.first_breach_at, started_at=ts)
        db.add(inc)
        await db.flush()
        repo.add_event(db, inc.id, "detected", act.value, act.first_breach_at)
        repo.add_event(db, inc.id, "suppressed" if parent else "opened", act.value, ts)
        changes = [Change("suppressed" if parent else "opened", inc, target, act.value, ts)]
        if target.type == "server" and key[1] in SERVER_AVAILABILITY:
            for child in await suppress_children(db, inc, ts):
                changes.append(Change("suppressed", child, await db.get(Target, child.target_id), child.value_at_open or 0.0, ts))
            await db.execute(update(Target).where(Target.host_id == target.id).values(status="unavailable"))  # «недоступний через сервер»
        return changes
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
        if target.type == "server" and key[1] in SERVER_AVAILABILITY:
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
        _states.pop((child.target_id, child.metric, child.instance), None)
        changes.append(Change("resolved", child, await db.get(Target, child.target_id), child.value_at_open or 0.0, ts))
    return changes


async def refresh_status(db: AsyncSession, target: Target, server_down: bool | None = None) -> None:
    """server_down: відомо викликачеві (ingest перевіряє раз на пакет); None – запитати в БД."""
    live = await repo.live_for_target(db, target.id)
    if server_down is None:
        server_down = bool(target.host_id and target.type != "server" and await repo.server_down(db, target.host_id))
    if server_down or any(i.metric in AVAILABILITY_METRICS for i in live):
        target.status = "unavailable"
    elif any(i.severity == "critical" for i in live):
        target.status = "critical"
    elif live:
        target.status = "warning"
    else:
        target.status = "ok"


async def process(db: AsyncSession, target: Target, points: list[Point], server_down: bool | None = None) -> list[Change]:
    """points – лише свіжі записи; пізні з буфера агента сюди не потрапляють (ТЗ 5.1)."""
    latest: dict[tuple[str, str], Point] = {}
    for p in sorted(points, key=lambda x: x.ts):
        latest[(p.metric, p.instance)] = p
    changes: list[Change] = []
    for (metric, instance), p in latest.items():
        th = await thresholds.resolve(db, target, metric)
        if th is None:
            continue
        key = (target.id, metric, instance)
        state = await _state(db, key)
        value = await _aggregate(db, target.id, p, th)
        _states[key], actions = step(state, th, value, p.ts)
        for act in actions:
            changes += await _apply(db, target, key, act, p.ts)
    await refresh_status(db, target, server_down)
    for c in changes:
        if c.kind in ("opened", "escalated"):
            await diagnosis.diagnose_incident(db, c.incident, target, c.ts)
        log.info("інцидент %s", c.kind, extra={"incident_id": c.incident.id, "target_id": c.target.id,
                                              "metric": c.incident.metric, "severity": c.incident.severity})
    await outbox.enqueue(db, changes)
    if latest:
        publish_after_commit(db, target.owner_id, events.metrics_event(
            target, {k: (p.ts, p.value) for k, p in latest.items()}))
    for c in changes:
        publish_after_commit(db, c.target.owner_id, events.incident_event(c.incident, c.target.name, c.kind))
    return changes
