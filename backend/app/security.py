import hashlib
import secrets
from typing import NamedTuple
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


MAX_PASSWORD_BYTES = 72  # bcrypt 5 не приймає довші паролі (кирилична літера – 2 байти)


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode()
    return len(raw) <= MAX_PASSWORD_BYTES and bcrypt.checkpw(raw, password_hash.encode())


def create_access_token(user_id: int, token_version: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    return jwt.encode({"sub": str(user_id), "tv": token_version, "exp": exp}, settings.jwt_secret, ALGORITHM)


class Claims(NamedTuple):
    user_id: int
    token_version: int
    exp: float  # unix-час закінчення дії токена


def decode_access_token(token: str) -> Claims | None:
    """None, якщо токен недійсний чи прострочений."""
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return Claims(int(data["sub"]), int(data["tv"]), float(data["exp"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_agent_token() -> str:
    return "vgl_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Токени агентів і коди прив'язки зберігаються лише як SHA-256: вони випадкові й довгі, повільний bcrypt не потрібен."""
    return hashlib.sha256(token.encode()).hexdigest()
