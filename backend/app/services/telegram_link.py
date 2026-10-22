import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import Conflict
from app.models import User
from app.notify import outbox
from app.security import hash_token

CODE_TTL = timedelta(minutes=10)


async def create_link(db: AsyncSession, user: User) -> dict:
    code = secrets.token_urlsafe(8)
    user.tg_link_code_hash = hash_token(code)
    user.tg_link_expires = datetime.now(timezone.utc) + CODE_TTL
    bot = settings.telegram_bot_username
    return {"code": code, "url": f"https://t.me/{bot}?start={code}" if bot else None, "expires_in_s": int(CODE_TTL.total_seconds())}


def unlink(user: User) -> None:
    user.telegram_chat_id = None
    user.tg_link_code_hash = user.tg_link_expires = None


async def link_by_code(db: AsyncSession, code: str, chat_id: int) -> User | None:
    """Викликається ботом: код одноразовий, діє 10 хв."""
    user = await db.scalar(select(User).where(User.tg_link_code_hash == hash_token(code)))
    if not user or not user.tg_link_expires or user.tg_link_expires < datetime.now(timezone.utc):
        return None
    other = await db.scalar(select(User).where(User.telegram_chat_id == chat_id, User.id != user.id))
    if other:
        other.telegram_chat_id = None  # один чат – один обліковий запис
    user.telegram_chat_id, user.tg_link_code_hash, user.tg_link_expires = chat_id, None, None
    return user


def send_test(db: AsyncSession, user: User) -> None:
    if user.telegram_chat_id is None:
        raise Conflict("Telegram не підключено", code="telegram_not_linked")
    outbox.enqueue_test(db, user.telegram_chat_id)
