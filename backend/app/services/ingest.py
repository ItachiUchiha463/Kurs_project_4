import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, AuthError, TooManyRequests
from app.metric_catalog import AGENT_METRICS, PERCENT_METRICS
from app.repositories import metrics as metrics_repo
from app.repositories import targets as targets_repo
from app.models import Target
from app.schemas.targets import ContainerInfo, DatabaseInfo, IngestBatch, IngestOut, IngestRecord, IngestRejected
from app.security import hash_token
from app.services import pipeline

log = logging.getLogger("vigil.ingest")
MAX_BATCH = 500
MAX_INSTANCE_LEN = 100
MAX_CONTAINERS = 100  # виявлених контейнерів на один сервер (ТЗ 2.4)
GONE_HIDE_AFTER = timedelta(hours=24)  # контейнер, що зник із Docker, ховається через добу (ТЗ 5.3)
_last_ingest: dict[int, float] = {}  # shortcut: у пам'яті процесу; рівно один процес (ТЗ розд. 3), при масштабуванні – у БД


_series_seen: dict[int, tuple[float, set[tuple[str, str]]]] = {}  # (коли завантажено, відомі ряди) кожного об'єкта: захист від безмежного росту
SERIES_TTL_S = 3600  # раз на годину список перечитується, щоб зниклі ряди (змінні диски) звільняли місце


async def _known_series(db: AsyncSession, target_id: int) -> set[tuple[str, str]]:
    loaded = _series_seen.get(target_id)
    if loaded is None or time.monotonic() - loaded[0] > SERIES_TTL_S:
        rows = await db.execute(text("SELECT DISTINCT name, instance FROM metrics WHERE target_id = :t AND ts > now() - interval '1 day'"),
                                {"t": target_id})
        _series_seen[target_id] = (time.monotonic(), {(n, i) for n, i in rows})
    return _series_seen[target_id][1]


def forget_target(target_id: int) -> None:
    _last_ingest.pop(target_id, None)
    _series_seen.pop(target_id, None)


def check_record(rec: IngestRecord, host_name: str, ts: datetime, now: datetime) -> str | None:
    """Причина відхилення запису або None (ТЗ розд. 6)."""
    if rec.host != host_name:
        return "host не збігається з об'єктом токена"
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


async def sync_containers(db: AsyncSession, server: Target, found: list[ContainerInfo], now: datetime,
                          databases: list[DatabaseInfo] = ()) -> dict[str, Target]:
    """Автовиявлення (ТЗ 5.3, 5.4): новий контейнер чи БД стає дочірнім об'єктом сервера, а зниклий ховається через 24 год.

    Ключ словника – те саме «docker:<id>» / «postgres:<id>», що агент пише в поле target записів.
    """
    children = {c.external_id: c for c in await db.scalars(
        select(Target).where(Target.host_id == server.id, Target.source == "discovered"))}
    wanted = [(f"docker:{i.id}", "container", "docker", i.name, i.image) for i in found[:MAX_CONTAINERS]]
    wanted += [(f"{i.engine}:{i.id}", "database", i.engine, i.name, "PostgreSQL") for i in databases[:MAX_CONTAINERS]]
    seen = set()
    for key, kind, check_type, name, address in wanted:
        seen.add(key)
        child = children.get(key)
        if child is None:
            child = Target(owner_id=server.owner_id, name=name, type=kind, check_type=check_type, source="discovered",
                           host_id=server.id, external_id=key, address=address, interval_s=server.interval_s)
            db.add(child)
            children[key] = child
        else:
            child.name, child.address = name, address
    for key, child in children.items():
        if key not in seen and not child.hidden and (child.last_seen or child.created_at or now) < now - GONE_HIDE_AFTER:
            child.hidden = True
    await db.flush()
    return children


async def ingest(db: AsyncSession, token: str, batch: IngestBatch, agent_time: datetime | None, agent_version: str | None,
                 agent_interval: int | None = None) -> IngestOut:
    records = batch.records
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
    discovered = bool(batch.containers or batch.databases or any(r.target for r in records))
    children = await sync_containers(db, target, batch.containers, now, batch.databases) if discovered else {}
    known: dict[int, set] = {}
    fresh: dict[int, list[pipeline.Point]] = {target.id: []}
    owners = {target.id: target}
    for i, rec in enumerate(records):
        ts = (rec.timestamp if rec.timestamp.tzinfo else rec.timestamp.replace(tzinfo=timezone.utc)) + offset
        reason = check_record(rec, target.name, ts, now)
        if reason:
            rejected.append(IngestRejected(index=i, reason=reason))
            continue
        owner = target
        if rec.target:
            owner = children.get(rec.target)
            if owner is None:
                rejected.append(IngestRejected(index=i, reason="невідомий дочірній об'єкт сервера"))
                continue
            if owner.hidden:
                continue  # прихований контейнер не моніториться: запис мовчки пропускаємо
        series = (rec.metric, rec.instance)
        seen = known.setdefault(owner.id, await _known_series(db, owner.id))
        if series not in seen and len(seen) >= settings.max_series_per_target:
            rejected.append(IngestRejected(index=i, reason=f"забагато різних рядів (ліміт {settings.max_series_per_target})"))
            continue
        seen.add(series)
        rows.append({"target_id": owner.id, "name": rec.metric, "instance": rec.instance, "value": rec.value, "ts": ts})
        if ts >= fresh_after:  # пізні записи з буфера лише зберігаються, інцидентів заднім числом не відкривають
            fresh.setdefault(owner.id, []).append(pipeline.Point(rec.metric, rec.instance, ts, rec.value))
            owners[owner.id] = owner
    accepted = len(rows)
    rows.append({"target_id": target.id, "name": "agent_alive", "instance": "", "value": 1.0, "ts": now})  # доказ, що агент живий
    fresh[target.id].append(pipeline.Point("agent_alive", "", now, 1.0))
    await metrics_repo.insert_many(db, rows)
    target.last_seen = now
    target.agent_version = agent_version
    target.clock_offset_s = offset.total_seconds() if agent_time else None
    await pipeline.process(db, target, fresh[target.id])
    for tid, points in fresh.items():
        if tid != target.id:
            owners[tid].last_seen = now
            await pipeline.process(db, owners[tid], points)
    if rejected:
        log.warning("відкинуто записи", extra={"target_id": target.id, "rejected": len(rejected)})
    return IngestOut(accepted=accepted, rejected=rejected)
