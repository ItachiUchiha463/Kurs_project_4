from datetime import datetime

import httpx

from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.net import split_host_port
from app.config import settings
from app.checks import ssrf
from app.errors import NotFound, QuotaExceeded, Unprocessable
from app.models import Target, User
from app.repositories import metrics as metrics_repo
from app.repositories import targets as repo
from app.schemas.targets import Point, TargetCreate, TargetCreated, TargetOut
from app.security import hash_token, new_agent_token

address_resolver = ssrf.resolve_public  # у тестах підміняється, щоб не ходити в DNS


def _out(target: Target, latest: dict[str, float] | None = None) -> TargetOut:
    out = TargetOut.model_validate(target)
    out.latest = latest or {}
    return out


def _probe_target(data: TargetCreate) -> tuple[str, int]:
    """(хост, порт) для перевірки адреси на SSRF при створенні."""
    if data.type == "server" or data.check_type == "ping":
        return data.address.strip(), 0
    if data.check_type == "tcp":
        return split_host_port(data.address)
    u = httpx.URL(data.address)
    return u.host, u.port or (443 if u.scheme == "https" else 80)


async def list_targets(db: AsyncSession, user: User) -> list[TargetOut]:
    targets = await repo.list_all(db, user.id)
    latest = await metrics_repo.latest(db, [t.id for t in targets])
    return [_out(t, latest.get(t.id)) for t in targets]


async def get_or_404(db: AsyncSession, user: User, target_id: int) -> Target:
    target = await repo.get(db, user.id, target_id)
    if not target:
        raise NotFound("Об'єкт не знайдено")
    return target


async def get_target(db: AsyncSession, user: User, target_id: int) -> TargetOut:
    target = await get_or_404(db, user, target_id)
    latest = await metrics_repo.latest(db, [target.id])
    return _out(target, latest.get(target.id))


async def create_target(db: AsyncSession, user: User, data: TargetCreate) -> TargetCreated:
    if await repo.count(db, user.id) >= settings.quota_targets:
        raise QuotaExceeded(f"Ліміт об'єктів: {settings.quota_targets}", details=[{"limit": settings.quota_targets}])
    if data.host_id is not None:
        host = await repo.get(db, user.id, data.host_id)
        if not host or host.type != "server":
            raise NotFound("Сервер для прив'язки не знайдено")
    if data.type == "service" or data.ping_enabled:
        try:
            await address_resolver(*_probe_target(data))
        except ssrf.BlockedAddress:
            raise Unprocessable("Адреса недоступна з інтернету – внутрішні сервіси підключайте через агента",
                                details=[{"field": "address", "message": "Адреса недоступна з інтернету"}]) from None
    token = new_agent_token() if data.type == "server" else None
    if data.type == "server":
        check_type = "agent"
    else:
        check_type = data.check_type
    target = repo.add(
        db, user.id, name=data.name, type=data.type, address=data.address, interval_s=data.interval_s,
        expected_status=data.expected_status, host_id=data.host_id if data.type == "service" else None, check_type=check_type,
        ping_enabled=data.ping_enabled and data.type == "server", agent_token_hash=hash_token(token) if token else None)
    await db.flush()
    return TargetCreated(**_out(target).model_dump(), agent_token=token)


async def rotate_token(db: AsyncSession, user: User, target_id: int) -> str:
    target = await get_or_404(db, user, target_id)
    if target.type != "server":
        raise NotFound("Токен є лише в серверів")
    token = new_agent_token()
    target.agent_token_hash = hash_token(token)
    return token


async def delete_target(db: AsyncSession, user: User, target_id: int) -> None:
    if not await repo.remove(db, user.id, target_id):
        raise NotFound("Об'єкт не знайдено")
    from app import background  # імпорт тут, щоб не тягнути фонові задачі при завантаженні модуля
    from app.services import ingest, pipeline
    for forget in (pipeline.forget_target, ingest.forget_target, background.forget_target):
        forget(target_id)


async def metric_series(db: AsyncSession, user: User, target_id: int, name: str, instance: str,
                        start: datetime, end: datetime) -> list[Point]:
    target = await get_or_404(db, user, target_id)
    rows = await metrics_repo.series(db, target.id, name, instance, start, end)
    return [Point(ts=ts, value=v) for ts, v in rows]
