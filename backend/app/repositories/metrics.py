from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import metrics

LONG_RANGE = timedelta(hours=24)


async def insert_many(db: AsyncSession, rows: list[dict]) -> None:
    if rows:
        await db.execute(insert(metrics), rows)


async def latest(db: AsyncSession, target_ids: list[int]) -> dict[int, dict[str, float]]:
    """Останнє значення кожного ряду за 15 хв; ключ – name або name:instance. target_ids уже відфільтровано за власником."""
    if not target_ids:
        return {}
    rows = await db.execute(text("""
        SELECT DISTINCT ON (target_id, name, instance) target_id, name, instance, value
        FROM metrics WHERE target_id = ANY(:ids) AND ts > :since
        ORDER BY target_id, name, instance, ts DESC"""),
        {"ids": target_ids, "since": datetime.now(timezone.utc) - timedelta(minutes=15)})
    out: dict[int, dict[str, float]] = {}
    for tid, name, inst, value in rows:
        out.setdefault(tid, {})[f"{name}:{inst}" if inst else name] = value
    return out


async def series(db: AsyncSession, target_id: int, name: str, instance: str,
                 start: datetime, end: datetime, max_points: int = 300) -> list[tuple[datetime, float]]:
    """target_id перевіряє викликач (сервіс) через репозиторій targets з owner_id.

    Період понад добу береться з безперервного агрегату metrics_5m (сирі дані стискаються й живуть 30 днів).
    """
    step = max(int((end - start).total_seconds() // max_points), 1)
    if end - start > LONG_RANGE:
        sql = """SELECT time_bucket(make_interval(secs => :step), bucket) AS b, avg(avg_value)
                 FROM metrics_5m WHERE target_id = :tid AND name = :name AND instance = :inst AND bucket >= :s AND bucket < :e
                 GROUP BY b ORDER BY b"""
        step = max(step, 300)
    else:
        sql = """SELECT time_bucket(make_interval(secs => :step), ts) AS b, avg(value)
                 FROM metrics WHERE target_id = :tid AND name = :name AND instance = :inst AND ts >= :s AND ts < :e
                 GROUP BY b ORDER BY b"""
    rows = await db.execute(text(sql), {"step": step, "tid": target_id, "name": name, "inst": instance, "s": start, "e": end})
    return [(b, v) for b, v in rows]
