from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.lower()))


async def get(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User))


def add(db: AsyncSession, email: str, full_name: str, password_hash: str) -> User:
    user = User(email=email.lower(), full_name=full_name, password_hash=password_hash)
    db.add(user)
    return user
