from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AuthError, Conflict, Forbidden
from app.models import User
from app.repositories import users
from app.schemas.auth import LoginIn, RegisterIn
from app.security import create_access_token, hash_password, verify_password

# Один і той самий текст для «немає такого email» і «невірний пароль»: за відповіддю не можна дізнатися, чи є email.
_BAD_CREDENTIALS = "Невірний email або пароль"
# Хеш-пустушка, щоб перевірка неіснуючого email займала стільки ж часу, скільки й справжнього.
_DUMMY_HASH = hash_password("dummy-password-1")


async def register(db: AsyncSession, data: RegisterIn) -> str:
    if settings.registration_mode == "closed":
        raise Forbidden("Реєстрацію закрито", code="registration_closed")
    user = users.add(db, data.email, data.full_name, hash_password(data.password))
    try:
        await db.flush()
    except IntegrityError:
        # без «email уже існує» (ТЗ розд. 6)
        raise Conflict("Не вдалося зареєструватися з цим email") from None
    return create_access_token(user.id, user.token_version)


async def login(db: AsyncSession, data: LoginIn) -> str:
    user = await users.get_by_email(db, data.email)
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise AuthError(_BAD_CREDENTIALS)
    if user.status != "active":
        raise Forbidden("Обліковий запис заблоковано", code="account_blocked")
    return create_access_token(user.id, user.token_version)


async def user_from_token(db: AsyncSession, user_id: int, token_version: int) -> User:
    user = await users.get(db, user_id)
    if not user or user.status != "active" or user.token_version != token_version:
        raise AuthError("Сесію завершено")
    return user
