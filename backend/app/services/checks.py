"""Застосування результатів серверних перевірок і контролю агентів: ті самі метрики й конвеєр, що й для /ingest."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.http import CheckResult, check_http
from app.models import Target
from app.repositories import metrics as metrics_repo
from app.services import pipeline

AGENT_DEAD_AFTER_INTERVALS = 3  # ТЗ 5.2: даних немає довше за 3 інтервали → agent_alive = 0


async def _store(db: AsyncSession, target: Target, points: list[pipeline.Point]) -> list[pipeline.Change]:
    await metrics_repo.insert_many(db, [{"target_id": target.id, "name": p.metric, "instance": p.instance,
                                         "value": p.value, "ts": p.ts} for p in points])
    return await pipeline.process(db, target, points)


async def run_http_check(db: AsyncSession, target: Target, checker=None) -> CheckResult:
    result = await (checker or check_http)(target.address, target.expected_status)
    now = datetime.now(timezone.utc)
    points = [pipeline.Point("available", "", now, result.available),
              pipeline.Point("status_code", "", now, result.status_code)]
    if result.response_ms is not None:
        points.append(pipeline.Point("response_ms", "", now, result.response_ms))
    target.last_seen = now
    await _store(db, target, points)
    return result


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
