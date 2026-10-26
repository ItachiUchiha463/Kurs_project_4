"""Застосування результатів серверних перевірок і контролю агентів: ті самі метрики й конвеєр, що й для /ingest."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.http import CheckResult, check_http
from app.checks.net import check_ping, check_tcp
from app.models import Target
from app.repositories import metrics as metrics_repo
from app.services import pipeline

AGENT_DEAD_AFTER_INTERVALS = 3  # ТЗ 5.2: даних немає довше за 3 інтервали → agent_alive = 0


async def _store(db: AsyncSession, target: Target, points: list[pipeline.Point]) -> list[pipeline.Change]:
    await metrics_repo.insert_many(db, [{"target_id": target.id, "name": p.metric, "instance": p.instance,
                                         "value": p.value, "ts": p.ts} for p in points])
    return await pipeline.process(db, target, points)


def _points(result: CheckResult, now: datetime, prefix: str, with_status: bool) -> list[pipeline.Point]:
    """prefix «ping_» – результат ping сервера (ping_available, ping_ms), інакше available / response_ms."""
    pts = [pipeline.Point(f"{prefix}available", "", now, result.available)]
    if with_status:
        pts.append(pipeline.Point("status_code", "", now, result.status_code))
    if result.response_ms is not None:
        pts.append(pipeline.Point("ping_ms" if prefix else "response_ms", "", now, result.response_ms))
    if result.packet_loss is not None and result.available:  # при повній втраті про якість зв'язку не йдеться: це вже інцидент доступності
        pts.append(pipeline.Point("packet_loss", "", now, result.packet_loss))
    return pts


async def run_check(db: AsyncSession, target: Target, checker=None) -> CheckResult:
    """Перевірка за типом об'єкта: http / tcp / ping для сервісу, ping для сервера з ping_enabled.
    `checker` підміняє виконавця в тестах (для http сигнатура (url, expected_status), для tcp і ping – (address))."""
    now = datetime.now(timezone.utc)
    if target.type == "server":
        result = await (checker or check_ping)(target.address)
        points = _points(result, now, "ping_", False)
    elif target.check_type == "tcp":
        result = await (checker or check_tcp)(target.address)
        points = _points(result, now, "", False)
    elif target.check_type == "ping":
        result = await (checker or check_ping)(target.address)
        points = _points(result, now, "", False)
    else:
        result = await (checker or check_http)(target.address, target.expected_status)
        points = _points(result, now, "", True)
    # last_seen сервера оновлює агент: за ним судять, чи живий агент, а ping про це нічого не каже
    if target.type != "server":
        target.last_seen = now
    await _store(db, target, points)
    return result


run_http_check = run_check  # назва з MVP: тести й виклики лишаються чинними


async def check_agents(db: AsyncSession, now: datetime | None = None) -> int:
    """Сервери, від яких давно немає даних: agent_alive = 0. «Живий» агент сам пише agent_alive = 1 в /ingest."""
    now = now or datetime.now(timezone.utc)
    servers = await db.scalars(select(Target).where(
        Target.type == "server", Target.enabled, Target.agent_token_hash.is_not(None), Target.last_seen.is_not(None)))
    dead = 0
    for t in servers:
        if now - t.last_seen > timedelta(seconds=AGENT_DEAD_AFTER_INTERVALS * t.effective_interval_s):
            state = pipeline._states.get((t.id, "agent_alive", ""))
            if state and state.incident:  # інцидент уже відкритий: не пишемо той самий 0 щоп'ятнадцять секунд
                continue
            dead += 1
            await _store(db, t, [pipeline.Point("agent_alive", "", now, 0)])
    return dead
