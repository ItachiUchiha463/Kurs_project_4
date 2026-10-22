"""Конвеєр обробки метрик (ТЗ 3.1, кроки 4–7): значення → пороги → інциденти → стан об'єкта."""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import AVAILABILITY_METRICS, DEFAULT_THRESHOLDS
from app.engine.thresholds import Deescalate, Escalate, Open, Resolve, State, Threshold, step
from app.models import Incident, Target
from app.repositories import incidents as repo
from app.notify import outbox
from app.services import diagnosis

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
    fn = "avg" if th.agg == "avg" else "max"
    row = await db.execute(text(
        f"SELECT {fn}(value) FROM metrics WHERE target_id = :t AND name = :n AND instance = :i AND ts > :s AND ts <= :e"),
        {"t": target_id, "n": p.metric, "i": p.instance, "s": p.ts - timedelta(seconds=th.window_s), "e": p.ts})
    value = row.scalar()  # None, лише якщо вікно порожнє
    return p.value if value is None else value


async def _state(db: AsyncSession, key: Key) -> State:
    if key not in _states:
        live = await repo.get_live(db, *key)
        _states[key] = State(incident=live.severity) if live else State()
    return _states[key]


def forget(target_id: int, metric: str, instance: str) -> None:
    """Викликається після ручного закриття: оцінювач починає ряд з чистого стану."""
    _states.pop((target_id, metric, instance), None)


async def _apply(db: AsyncSession, target: Target, key: Key, act, ts: datetime) -> Change | None:
    if isinstance(act, Open):
        inc = Incident(owner_id=target.owner_id, target_id=target.id, metric=key[1], instance=key[2],
                       severity=act.severity, status="open", value_at_open=act.value,
                       first_breach_at=act.first_breach_at, started_at=ts)
        db.add(inc)
        await db.flush()
        repo.add_event(db, inc.id, "detected", act.value, act.first_breach_at)
        repo.add_event(db, inc.id, "opened", act.value, ts)
        return Change("opened", inc, target, act.value, ts)
    inc = await repo.get_live(db, *key)
    if inc is None:  # інцидент закрили вручну, поки стан ще пам'ятав його
        return None
    if isinstance(act, Escalate):
        inc.severity = act.severity
        repo.add_event(db, inc.id, "escalated", act.value, ts)
        return Change("escalated", inc, target, act.value, ts)
    if isinstance(act, Deescalate):
        inc.severity = act.severity
        repo.add_event(db, inc.id, "deescalated", act.value, ts)
        return Change("deescalated", inc, target, act.value, ts)
    if isinstance(act, Resolve):
        inc.status, inc.resolved_at = "resolved", ts
        repo.add_event(db, inc.id, "resolved", act.value, ts, note="автоматично")
        return Change("resolved", inc, target, act.value, ts)
    return None


async def refresh_status(db: AsyncSession, target: Target) -> None:
    live = await repo.live_for_target(db, target.id)
    if any(i.metric in AVAILABILITY_METRICS for i in live):
        target.status = "unavailable"
    elif any(i.severity == "critical" for i in live):
        target.status = "critical"
    elif live:
        target.status = "warning"
    else:
        target.status = "ok"


async def process(db: AsyncSession, target: Target, points: list[Point]) -> list[Change]:
    """points – лише свіжі записи; пізні з буфера агента сюди не потрапляють (ТЗ 5.1)."""
    latest: dict[tuple[str, str], Point] = {}
    for p in sorted(points, key=lambda x: x.ts):
        latest[(p.metric, p.instance)] = p
    changes: list[Change] = []
    for (metric, instance), p in latest.items():
        th = DEFAULT_THRESHOLDS.get(metric)
        if th is None:
            continue
        key = (target.id, metric, instance)
        state = await _state(db, key)
        value = await _aggregate(db, target.id, p, th)
        _states[key], actions = step(state, th, value, p.ts)
        for act in actions:
            change = await _apply(db, target, key, act, p.ts)
            if change:
                changes.append(change)
    await refresh_status(db, target)
    for c in changes:
        if c.kind in ("opened", "escalated"):
            await diagnosis.diagnose_incident(db, c.incident, target, c.ts)
        log.info("інцидент %s", c.kind, extra={"incident_id": c.incident.id, "target_id": target.id,
                                              "metric": c.incident.metric, "severity": c.incident.severity})
    await outbox.enqueue(db, changes)
    return changes
