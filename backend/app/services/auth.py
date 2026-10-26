import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, AuthError, Conflict, Forbidden, TooManyRequests
from app.models import User
from app.ratelimit import FailureLock
from app.repositories import users
from app.schemas.auth import LoginIn, RegisterIn
from app.notify import messages, telegram
from app.security import create_access_token, hash_password, hash_token, verify_password

log = logging.getLogger("vigil.auth")
RESET_TTL = timedelta(minutes=30)
# Один і той самий текст для «немає такого email» і «невірний пароль»: за відповіддю не можна дізнатися, чи є email.
_BAD_CREDENTIALS = "Невірний email або пароль"
# Хеш-пустушка, щоб перевірка неіснуючого email займала стільки ж часу, скільки й справжнього.
_DUMMY_HASH = hash_password("dummy-password-1")
# N невдалих входів поспіль з однієї IP на один email – блокування (ТЗ розд. 6); діє й для неіснуючих email, тож нічого не розкриває
login_failures = FailureLock(settings.login_lock_after, settings.login_lock_s)


async def register(db: AsyncSession, data: RegisterIn) -> str:
    if settings.registration_mode == "closed":
        raise Forbidden("Реєстрацію закрито", code="registration_closed")
    if await users.count(db) >= settings.global_users:
        raise Forbidden("Сервіс заповнений: реєстрацію тимчасово закрито", code="registration_closed")
    user = users.add(db, data.email, data.full_name, await asyncio.to_thread(hash_password, data.password))
    try:
        await db.flush()
    except IntegrityError:
        # без «email уже існує» (ТЗ розд. 6)
        raise Conflict("Не вдалося зареєструватися з цим email") from None
    return create_access_token(user.id, user.token_version)


async def login(db: AsyncSession, data: LoginIn, ip: str = "") -> str:
    email = f"{data.email.lower()}|{ip}"  # ключ з IP: сторонній не заблокує чужий обліковий запис
    if login_failures.locked(email):
        raise TooManyRequests("Забагато невдалих спроб входу. Спробуйте за 15 хвилин")
    user = await users.get_by_email(db, data.email)
    # bcrypt ~0,3 с: у потоці, щоб не зупиняти event loop
    ok = await asyncio.to_thread(verify_password, data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        login_failures.fail(email)
        raise AuthError(_BAD_CREDENTIALS)
    login_failures.ok(email)
    if user.status != "active":
        raise Forbidden("Обліковий запис заблоковано", code="account_blocked")
    return create_access_token(user.id, user.token_version)


async def user_from_token(db: AsyncSession, user_id: int, token_version: int) -> User:
    user = await users.get(db, user_id)
    if not user or user.status != "active" or user.token_version != token_version:
        raise AuthError("Сесію завершено")
    return user


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Надсилає посилання для скидання в прив'язаний Telegram. Назовні – завжди та сама відповідь: за нею не дізнатися, чи є такий email.

    shortcut: надсилання йде в тому ж запиті, тож відповідь для існуючого email трохи довша; для 100 користувачів це не критично.
    """
    user = await users.get_by_email(db, email)
    bot = telegram.get_bot()
    if not user or user.status != "active" or user.telegram_chat_id is None or bot is None:
        return
    token = secrets.token_urlsafe(32)
    user.pwd_reset_hash, user.pwd_reset_expires = hash_token(token), datetime.now(timezone.utc) + RESET_TTL
    try:
        await bot.send(user.telegram_chat_id, messages.render("reset", url=f"{settings.public_url.rstrip('/')}/reset?token={token}"))
    except telegram.TelegramError as e:
        log.warning("не вдалося надіслати посилання для скидання пароля: %s", e)


async def reset_password(db: AsyncSession, token: str, password: str) -> None:
    from sqlalchemy import select
    user = await db.scalar(select(User).where(User.pwd_reset_hash == hash_token(token)))
    if not user or not user.pwd_reset_expires or user.pwd_reset_expires < datetime.now(timezone.utc):
        raise AppError("Посилання недійсне або прострочене. Запросіть нове", code="invalid_reset_token")
    user.password_hash = await asyncio.to_thread(hash_password, password)
    user.pwd_reset_hash = user.pwd_reset_expires = None  # посилання одноразове
    user.token_version += 1  # усі наявні сесії завершуються
    login_failures.reset()


async def logout_all(user: User) -> None:
    """«Вийти на всіх пристроях»: усі видані JWT, зокрема поточний, перестають діяти."""
    user.token_version += 1
