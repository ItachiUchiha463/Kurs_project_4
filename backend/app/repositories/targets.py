"""Усі методи, крім get_by_agent_token, приймають owner_id: чужий об'єкт для них «не існує» (ТЗ розд. 3).

Це ключ до ізоляції даних користувачів: жоден запит не вибирає об'єкт лише за id, а завжди «id І owner_id».
Тому, навіть знаючи чужий id, користувач отримає «не знайдено» (404), а не чужі дані.
"""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target


async def list_all(db: AsyncSession, owner_id: int) -> list[Target]:
    """Усі видимі об'єкти користувача (приховані контейнери не показуються)."""
    return list(await db.scalars(select(Target).where(Target.owner_id == owner_id, Target.hidden.is_(False)).order_by(Target.id)))


async def children(db: AsyncSession, owner_id: int, host_id: int) -> list[Target]:
    """Виявлені контейнери й бази сервера."""
    return list(await db.scalars(select(Target).where(Target.owner_id == owner_id, Target.host_id == host_id,
                                                      Target.source == "discovered").order_by(Target.name)))


async def get(db: AsyncSession, owner_id: int, target_id: int) -> Target | None:
    """Об'єкт за id, але лише якщо він належить цьому користувачеві."""
    return await db.scalar(select(Target).where(Target.id == target_id, Target.owner_id == owner_id))


async def count(db: AsyncSession, owner_id: int) -> int:
    """Скільки об'єктів додав сам користувач (виявлені автоматично в ліміт не входять)."""
    return await db.scalar(select(func.count()).select_from(Target).where(Target.owner_id == owner_id, Target.source == "manual"))


def add(db: AsyncSession, owner_id: int, **fields) -> Target:
    """Додає новий об'єкт у сесію (запис у БД відбудеться разом із транзакцією)."""
    target = Target(owner_id=owner_id, **fields)
    db.add(target)
    return target


async def remove(db: AsyncSession, owner_id: int, target_id: int) -> bool:
    """Видаляє об'єкт і (для сервера) його виявлені контейнери й бази. True, якщо щось видалено."""
    await db.execute(delete(Target).where(Target.host_id == target_id, Target.owner_id == owner_id, Target.source == "discovered"))  # контейнери зникають разом із сервером
    res = await db.execute(delete(Target).where(Target.id == target_id, Target.owner_id == owner_id))
    return res.rowcount > 0


async def get_by_agent_token(db: AsyncSession, token_hash: str) -> Target | None:
    """Єдиний вхід без owner_id: власника визначає сам токен агента."""
    return await db.scalar(select(Target).where(Target.agent_token_hash == token_hash))
