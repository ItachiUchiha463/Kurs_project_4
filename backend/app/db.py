"""Підключення до БД: асинхронний двигун SQLAlchemy й одна сесія на HTTP-запит."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# pool_pre_ping: перед видачею з'єднання з пулу перевіряє, що воно ще живе (після перезапуску БД не буде помилок).
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
# expire_on_commit=False: після коміту об'єкти лишаються придатними для читання (інакше кожне звернення до поля
# після коміту викликало б новий запит до БД).
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Базовий клас усіх моделей ORM (app/models/core.py)."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """Одна сесія на запит: коміт при успіху, відкат при винятку.

    Транзакційність на рівні запиту: якщо обробник маршруту кинув помилку (навіть після кількох записів),
    відкочується все, а не лише частина. Тому в сервісах немає окремих commit() – вони лише змінюють об'єкти.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
