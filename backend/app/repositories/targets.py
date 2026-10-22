"""Усі методи, крім get_by_agent_token, приймають owner_id: чужий об'єкт для них «не існує» (ТЗ розд. 3)."""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target


async def list_all(db: AsyncSession, owner_id: int) -> list[Target]:
    return list(await db.scalars(select(Target).where(Target.owner_id == owner_id).order_by(Target.id)))


async def get(db: AsyncSession, owner_id: int, target_id: int) -> Target | None:
    return await db.scalar(select(Target).where(Target.id == target_id, Target.owner_id == owner_id))


async def count(db: AsyncSession, owner_id: int) -> int:
    return await db.scalar(select(func.count()).select_from(Target).where(Target.owner_id == owner_id))


def add(db: AsyncSession, owner_id: int, **fields) -> Target:
    target = Target(owner_id=owner_id, **fields)
    db.add(target)
    return target


async def remove(db: AsyncSession, owner_id: int, target_id: int) -> bool:
    res = await db.execute(delete(Target).where(Target.id == target_id, Target.owner_id == owner_id))
    return res.rowcount > 0


async def get_by_agent_token(db: AsyncSession, token_hash: str) -> Target | None:
    """Єдиний вхід без owner_id: власника визначає сам токен агента."""
    return await db.scalar(select(Target).where(Target.agent_token_hash == token_hash))
