import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, AuthError
from app.metric_catalog import AGENT_METRICS, PERCENT_METRICS
from app.repositories import metrics as metrics_repo
from app.repositories import targets as targets_repo
from app.schemas.targets import IngestOut, IngestRecord, IngestRejected
from app.security import hash_token

log = logging.getLogger("vigil.ingest")
MAX_BATCH = 500
_last_ingest: dict[int, float] = {}  # shortcut: у пам'яті процесу; рівно один процес (ТЗ розд. 3), при масштабуванні – у БД


class RateLimited(AppError):
    status, code = 429, "rate_limited"


def check_record(rec: IngestRecord, host_name: str, ts: datetime, now: datetime) -> str | None:
    """Причина відхилення запису або None (ТЗ розд. 6)."""
    if rec.host != host_name:
        return "host не збігається з об'єктом токена"
    if rec.target is not None:
        return "дочірні об'єкти поки не підтримуються"
    if rec.metric not in AGENT_METRICS:
        return "невідома метрика"
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
                 agent_time: datetime | None, agent_version: str | None) -> IngestOut:
    target = await targets_repo.get_by_agent_token(db, hash_token(token))
    if not target or not target.enabled:
        raise AuthError("Невірний токен агента")
    if len(records) > MAX_BATCH:
        raise AppError(f"Не більше {MAX_BATCH} записів у пакеті", code="batch_too_large")
    mono = time.monotonic()
    if mono - _last_ingest.get(target.id, -1e9) < settings.ingest_min_interval_s:
        raise RateLimited("Занадто часті запити")
    _last_ingest[target.id] = mono

    now = datetime.now(timezone.utc)
    offset = clock_offset(agent_time, now)
    rows, rejected = [], []
    for i, rec in enumerate(records):
        ts = (rec.timestamp if rec.timestamp.tzinfo else rec.timestamp.replace(tzinfo=timezone.utc)) + offset
        reason = check_record(rec, target.name, ts, now)
        if reason:
            rejected.append(IngestRejected(index=i, reason=reason))
            continue
        rows.append({"target_id": target.id, "name": rec.metric, "instance": rec.instance, "value": rec.value, "ts": ts})
    await metrics_repo.insert_many(db, rows)
    target.last_seen = now
    target.agent_version = agent_version
    target.clock_offset_s = offset.total_seconds() if agent_time else None
    if rejected:
        log.warning("відкинуто записи", extra={"target_id": target.id, "rejected": len(rejected)})
    return IngestOut(accepted=len(rows), rejected=rejected)
