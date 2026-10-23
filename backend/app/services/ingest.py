import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, AuthError, TooManyRequests
from app.metric_catalog import AGENT_METRICS, PERCENT_METRICS
from app.repositories import metrics as metrics_repo
from app.repositories import targets as targets_repo
from app.schemas.targets import IngestOut, IngestRecord, IngestRejected
from app.security import hash_token
from app.services import pipeline

log = logging.getLogger("vigil.ingest")
MAX_BATCH = 500
MAX_INSTANCE_LEN = 100
_last_ingest: dict[int, float] = {}  # shortcut: у пам'яті процесу; рівно один процес (ТЗ розд. 3), при масштабуванні – у БД


_series_seen: dict[int, set[tuple[str, str]]] = {}  # відомі ряди кожного об'єкта: захист від безмежного росту


async def _known_series(db: AsyncSession, target_id: int) -> set[tuple[str, str]]:
    if target_id not in _series_seen:
        rows = await db.execute(text("SELECT DISTINCT name, instance FROM metrics WHERE target_id = :t AND ts > now() - interval '1 day'"),
                                {"t": target_id})
        _series_seen[target_id] = {(n, i) for n, i in rows}
    return _series_seen[target_id]


def forget_target(target_id: int) -> None:
    _last_ingest.pop(target_id, None)
    _series_seen.pop(target_id, None)


def check_record(rec: IngestRecord, host_name: str, ts: datetime, now: datetime) -> str | None:
    """Причина відхилення запису або None (ТЗ розд. 6)."""
    if rec.host != host_name:
        return "host не збігається з об'єктом токена"
    if rec.target is not None:
        return "дочірні об'єкти поки не підтримуються"
    if rec.metric not in AGENT_METRICS:
        return "невідома метрика"
    if len(rec.instance) > MAX_INSTANCE_LEN:
        return f"instance довший за {MAX_INSTANCE_LEN} символів"
    if rec.value != rec.value or rec.value in (float("inf"), float("-inf")):
        return "значення не є числом"
    if rec.value < 0 or (rec.metric in PERCENT_METRICS and rec.value > 100):
        return "значення поза допустимим діапазоном"
    if ts > now + timedelta(seconds=60):
        return "мітка часу з майбутнього"
    if ts < now - timedelta(hours=1):
        return "мітка часу старша за 1 годину"
    return None


def clock_offset(agent_time: datetime | None, now: datetime) -> timedelta:
    """Зсув годинника агента відносно сервера (ТЗ 5.1); без заголовка – 0."""
    return now - agent_time if agent_time else timedelta(0)


async def ingest(db: AsyncSession, token: str, records: list[IngestRecord],
                 agent_time: datetime | None, agent_version: str | None, agent_interval: int | None = None) -> IngestOut:
    target = await targets_repo.get_by_agent_token(db, hash_token(token))
    if not target or not target.enabled:
        raise AuthError("Невірний токен агента")
    if len(records) > MAX_BATCH:
        raise AppError(f"Не більше {MAX_BATCH} записів у пакеті", code="batch_too_large")
    mono = time.monotonic()
    if mono - _last_ingest.get(target.id, -1e9) < settings.ingest_min_interval_s:
        raise TooManyRequests("Занадто часті запити")
    _last_ingest[target.id] = mono

    now = datetime.now(timezone.utc)
    offset = clock_offset(agent_time, now)
    rows, rejected = [], []
    if agent_interval:
        target.agent_interval_s = max(15, min(3600, agent_interval))
    fresh_after = now - timedelta(seconds=2 * target.effective_interval_s)
    known = await _known_series(db, target.id)
    fresh: list[pipeline.Point] = []
    for i, rec in enumerate(records):
        ts = (rec.timestamp if rec.timestamp.tzinfo else rec.timestamp.replace(tzinfo=timezone.utc)) + offset
        reason = check_record(rec, target.name, ts, now)
        if reason:
            rejected.append(IngestRejected(index=i, reason=reason))
            continue
        series = (rec.metric, rec.instance)
        if series not in known and len(known) >= settings.max_series_per_target:
            rejected.append(IngestRejected(index=i, reason=f"забагато різних рядів (ліміт {settings.max_series_per_target})"))
            continue
        known.add(series)
        rows.append({"target_id": target.id, "name": rec.metric, "instance": rec.instance, "value": rec.value, "ts": ts})
        if ts >= fresh_after:  # пізні записи з буфера лише зберігаються, інцидентів заднім числом не відкривають
            fresh.append(pipeline.Point(rec.metric, rec.instance, ts, rec.value))
    accepted = len(rows)
    alive = {"target_id": target.id, "name": "agent_alive", "instance": "", "value": 1.0, "ts": now}
    rows.append(alive)  # будь-який пакет від агента – доказ, що він живий; закриває інцидент agent_alive = 0
    fresh.append(pipeline.Point("agent_alive", "", now, 1.0))
    await metrics_repo.insert_many(db, rows)
    target.last_seen = now
    target.agent_version = agent_version
    target.clock_offset_s = offset.total_seconds() if agent_time else None
    await pipeline.process(db, target, fresh)
    if rejected:
        log.warning("відкинуто записи", extra={"target_id": target.id, "rejected": len(rejected)})
    return IngestOut(accepted=accepted, rejected=rejected)
