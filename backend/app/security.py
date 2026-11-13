"""Криптографія й токени: паролі, JWT для користувачів, токени агентів.

Три різні механізми, бо захищають різне:
  1. Паролі користувачів – bcrypt (повільний за задумом, щоб перебір був дорогим; кожен хеш має власну «сіль»).
  2. Токен входу користувача (JWT) – підписаний, містить id користувача, версію токенів (token_version) і строк дії.
  3. Токен агента та одноразові коди – випадкові довгі рядки; у БД лише їхній SHA-256 (швидкий хеш тут доречний,
     бо джерело випадкове й довге: перебрати його неможливо).
"""
import hashlib
import secrets
from typing import NamedTuple
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"  # симетричний підпис: той самий JWT_SECRET підписує й перевіряє


def hash_password(password: str) -> str:
    """Хеш пароля для збереження в БД. bcrypt сам генерує сіль і вбудовує її в результат."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


MAX_PASSWORD_BYTES = 72  # bcrypt 5 не приймає довші паролі (кирилична літера – 2 байти)


def verify_password(password: str, password_hash: str) -> bool:
    """Чи збігається пароль із хешем. Занадто довгий пароль одразу вважається неправильним (bcrypt його не прийме)."""
    raw = password.encode()
    return len(raw) <= MAX_PASSWORD_BYTES and bcrypt.checkpw(raw, password_hash.encode())


def create_access_token(user_id: int, token_version: int) -> str:
    """Видає JWT. Поля: sub – id користувача, tv – версія токенів (див. нижче), exp – строк дії.

    token_version зберігається і в токені, і в користувача в БД. «Вийти на всіх пристроях» збільшує версію в БД,
    після чого всі раніше видані токени (з меншим tv) перестають діяти одразу, не чекаючи свого строку.
    """
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    return jwt.encode({"sub": str(user_id), "tv": token_version, "exp": exp}, settings.jwt_secret, ALGORITHM)


class Claims(NamedTuple):
    """Розібраний вміст дійсного токена."""
    user_id: int
    token_version: int
    exp: float  # unix-час закінчення дії токена


def decode_access_token(token: str) -> Claims | None:
    """None, якщо токен недійсний чи прострочений."""
    try:
        # jwt.decode сам перевіряє підпис і строк дії (exp); algorithms=[...] забороняє підміну алгоритму.
        data = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return Claims(int(data["sub"]), int(data["tv"]), float(data["exp"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_agent_token() -> str:
    """Новий токен агента: префікс «vgl_» (щоб його легко впізнати) + 32 випадкові байти."""
    return "vgl_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Токени агентів і коди прив'язки зберігаються лише як SHA-256: вони випадкові й довгі, повільний bcrypt не потрібен."""
    return hashlib.sha256(token.encode()).hexdigest()
