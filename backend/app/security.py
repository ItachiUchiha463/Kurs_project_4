import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, token_version: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    return jwt.encode({"sub": str(user_id), "tv": token_version, "exp": exp}, settings.jwt_secret, ALGORITHM)


def decode_access_token(token: str) -> tuple[int, int] | None:
    """(user_id, token_version) або None, якщо токен недійсний чи прострочений."""
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return int(data["sub"]), int(data["tv"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_agent_token() -> str:
    return "vgl_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Токени агентів і коди прив'язки зберігаються лише як SHA-256: вони випадкові й довгі, повільний bcrypt не потрібен."""
    return hashlib.sha256(token.encode()).hexdigest()
