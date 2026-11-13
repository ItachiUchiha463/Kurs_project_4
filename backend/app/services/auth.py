"""Автентифікація: реєстрація, вхід, підтвердження пошти, скидання пароля, вихід на всіх пристроях.

Головні принципи безпеки, які тут реалізовані (їх варто вміти пояснити на захисті):
  – паролі лише як bcrypt-хеші; токени для листів і скидання – лише як SHA-256-хеші, одноразові, із строком дії;
  – однакова відповідь на «немає такого email» і «неправильний пароль» (не можна перевірити, чи зареєстрований email);
  – обмеження перебору: блокування після N невдалих входів і ліміти на листи (захист від спаму в чужу пошту);
  – «вийти на всіх пристроях»: збільшення token_version анулює всі видані JWT миттєво.
"""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, AuthError, Conflict, Forbidden, TooManyRequests
from app.models import User
from app.ratelimit import FailureLock, SlidingWindow
from app.repositories import users
from app.schemas.auth import LoginIn, RegisterIn
from app.notify import mail, messages, telegram
from app.security import create_access_token, hash_password, hash_token, verify_password

log = logging.getLogger("vigil.auth")
RESET_TTL = timedelta(minutes=30)   # скільки діє посилання для скидання пароля
VERIFY_TTL = timedelta(hours=24)    # скільки діє посилання підтвердження пошти
verify_limiter = SlidingWindow(3, 3600)  # листів із підтвердженням на годину для одного email
forgot_limiter = SlidingWindow(3, 3600)  # скидань пароля на годину для одного email: захист від спаму в чужий Telegram
# Один і той самий текст для «немає такого email» і «неправильний пароль»: за відповіддю не можна дізнатися, чи є email.
_BAD_CREDENTIALS = "Неправильний email або пароль"
# Хеш-пустушка, щоб перевірка неіснуючого email займала стільки ж часу, скільки й справжнього.
_DUMMY_HASH = hash_password("dummy-password-1")
# N невдалих входів поспіль з однієї IP на один email – блокування (ТЗ розд. 6); діє й для неіснуючих email, тож нічого не розкриває
login_failures = FailureLock(settings.login_lock_after, settings.login_lock_s)


async def _send_verification(user: User) -> None:
    """Генерує одноразовий токен підтвердження, зберігає його ХЕШ і надсилає користувачеві лист з посиланням."""
    token = secrets.token_urlsafe(32)
    user.verify_hash, user.verify_expires = hash_token(token), datetime.now(timezone.utc) + VERIFY_TTL
    url = f"{settings.public_url.rstrip('/')}/verify?token={token}"
    try:
        await mail.send(user.email, "Підтвердіть пошту – Vigil",
                        f"Вітаємо, {user.full_name}!\n\nЩоб завершити реєстрацію у Vigil, відкрийте посилання (діє 24 години):\n{url}\n\n"
                        "Якщо ви не реєструвалися, просто проігноруйте цей лист.")
    except mail.MailError as e:
        log.warning("не вдалося надіслати лист із підтвердженням: %s", e)


async def register(db: AsyncSession, data: RegisterIn) -> str | None:
    """Токен входу; None, якщо спершу потрібно підтвердити пошту (налаштовано SMTP)."""
    if settings.registration_mode == "closed":
        raise Forbidden("Реєстрацію закрито", code="registration_closed")
    if await users.count(db) >= settings.global_users:
        raise Forbidden("Сервіс заповнений: реєстрацію тимчасово закрито", code="registration_closed")
    # Хешування bcrypt повільне (~0,3 с), тому виконується в окремому потоці, щоб не зупиняти весь сервер.
    user = users.add(db, data.email, data.full_name, await asyncio.to_thread(hash_password, data.password))
    try:
        await db.flush()
    except IntegrityError:
        # без «email уже існує» (ТЗ розд. 6)
        raise Conflict("Не вдалося зареєструватися з цим email") from None
    if mail.enabled():
        # Пошта налаштована: користувач має підтвердити email; токен входу не видаємо.
        await _send_verification(user)
        return None
    # Пошти немає: підтвердження неможливе, тому вважаємо email підтвердженим і одразу впускаємо.
    user.email_verified_at = datetime.now(timezone.utc)
    return create_access_token(user.id, user.token_version)


async def login(db: AsyncSession, data: LoginIn, ip: str = "") -> str:
    """Вхід за email і паролем. Повертає JWT або кидає помилку (неправильні дані, блокування, непідтверджена пошта)."""
    email = f"{data.email.lower()}|{ip}"  # ключ з IP: сторонній не заблокує чужий обліковий запис
    if login_failures.locked(email):
        raise TooManyRequests("Забагато невдалих спроб входу. Спробуйте за 15 хвилин")
    user = await users.get_by_email(db, data.email)
    # bcrypt ~0,3 с: у потоці, щоб не зупиняти event loop
    # Якщо користувача немає, перевіряємо пароль проти хеша-пустушки: час відповіді не видає, чи існує email.
    ok = await asyncio.to_thread(verify_password, data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        login_failures.fail(email)
        raise AuthError(_BAD_CREDENTIALS)
    login_failures.ok(email)
    if user.status != "active":
        raise Forbidden("Обліковий запис заблоковано", code="account_blocked")
    if user.email_verified_at is None:
        # Пошту ще не підтверджено: пробуємо надіслати новий лист (не частіше за ліміт) і відмовляємо у вході.
        resend = verify_limiter.hit(user.email)
        if resend:
            await _send_verification(user)
            await db.commit()  # виняток нижче відкотив би новий токен, і посилання з листа не спрацювало б
        raise Forbidden("Пошту не підтверджено. " + ("Ми надіслали новий лист: відкрийте посилання з нього (перевірте «Спам»)" if resend
                        else "Відкрийте посилання з останнього листа або спробуйте за годину"), code="email_not_verified")
    return create_access_token(user.id, user.token_version)


async def verify_email(db: AsyncSession, token: str) -> str:
    """Одноразове посилання з листа: підтверджує пошту й одразу впускає користувача."""
    # У БД збережено лише хеш токена, тому шукаємо за хешем отриманого токена.
    user = await db.scalar(select(User).where(User.verify_hash == hash_token(token)))
    if not user or not user.verify_expires or user.verify_expires < datetime.now(timezone.utc):
        raise AppError("Посилання недійсне або прострочене. Спробуйте увійти: ми надішлемо новий лист", code="invalid_verify_token")
    # Одноразовість: після підтвердження хеш і строк стираються, повторно посилання не спрацює.
    user.email_verified_at, user.verify_hash, user.verify_expires = datetime.now(timezone.utc), None, None
    return create_access_token(user.id, user.token_version)


async def user_from_token(db: AsyncSession, user_id: int, token_version: int) -> User:
    """Користувач за даними з JWT. Недійсний, якщо користувача немає/заблоковано або версія токена застаріла."""
    user = await users.get(db, user_id)
    if not user or user.status != "active" or user.token_version != token_version:
        raise AuthError("Сесію завершено")
    return user


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Надсилає посилання для скидання листом і в прив'язаний Telegram. Назовні – завжди та сама відповідь: за нею не дізнатися, чи є такий email.

    shortcut: надсилання йде в тому ж запиті, тож відповідь для існуючого email трохи довша; для 100 користувачів це не критично.
    """
    if not forgot_limiter.hit(email.lower()):  # не більше 3 листів на годину на один email; відповідь та сама
        return
    user = await users.get_by_email(db, email)
    if not user or user.status != "active":
        return  # мовчимо: зовні відповідь однакова
    token = secrets.token_urlsafe(32)
    url = f"{settings.public_url.rstrip('/')}/reset?token={token}"
    sent = False
    # Канал 1: Telegram (якщо прив'язано).
    bot = telegram.get_bot()
    if bot and user.telegram_chat_id is not None:
        try:
            await bot.send(user.telegram_chat_id, messages.render("reset", url=url))
            sent = True
        except telegram.TelegramError as e:
            log.warning("не вдалося надіслати посилання для скидання пароля в Telegram: %s", e)
    # Канал 2: пошта (якщо SMTP налаштовано й адресу підтверджено).
    if mail.enabled() and user.email_verified_at:
        try:
            await mail.send(user.email, "Скидання пароля – Vigil",
                            f"Щоб задати новий пароль, відкрийте посилання (діє 30 хвилин):\n{url}\n\nЯкщо ви не просили скидання, проігноруйте цей лист.")
            sent = True
        except mail.MailError as e:
            log.warning("не вдалося надіслати лист зі скиданням пароля: %s", e)
    if sent:
        # Токен зберігаємо, лише якщо його справді куди-небудь надіслали.
        user.pwd_reset_hash, user.pwd_reset_expires = hash_token(token), datetime.now(timezone.utc) + RESET_TTL


async def reset_password(db: AsyncSession, token: str, password: str) -> None:
    """Задає новий пароль за одноразовим посиланням і завершує всі сесії."""
    user = await db.scalar(select(User).where(User.pwd_reset_hash == hash_token(token)))
    if not user or not user.pwd_reset_expires or user.pwd_reset_expires < datetime.now(timezone.utc):
        raise AppError("Посилання недійсне або прострочене. Запросіть нове", code="invalid_reset_token")
    user.password_hash = await asyncio.to_thread(hash_password, password)
    user.pwd_reset_hash = user.pwd_reset_expires = None  # посилання одноразове
    user.token_version += 1  # усі наявні сесії завершуються


async def logout_all(user: User) -> None:
    """«Вийти на всіх пристроях»: усі видані JWT, зокрема поточний, перестають діяти."""
    user.token_version += 1
