"""Залежності FastAPI (Depends): те, що потрібне багатьом маршрутам.

FastAPI сам підставляє результат залежності в параметри функції-обробника. У маршрутах пишуть
`db: DbDep` (сесія БД) і `user: CurrentUser` (поточний користувач) – решту робить цей файл.
"""
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import AuthError
from app.models import User
from app.security import decode_access_token
from app.services import auth as auth_service

# scope="function": коміт виконується до відправки відповіді. За типового scope він іде ПІСЛЯ відповіді,
# тож невдалий коміт лишив би клієнта з 2xx, а запис – незбереженим.
DbDep = Annotated[AsyncSession, Depends(get_db, scope="function")]
# HTTPBearer читає заголовок «Authorization: Bearer <токен>». auto_error=False: помилку формуємо самі, у єдиному форматі.
_bearer = HTTPBearer(auto_error=False)


async def current_user(
    db: DbDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None
) -> User:
    """Автентифікує запит: розбирає JWT і повертає користувача або кидає AuthError (HTTP 401)."""
    parsed = decode_access_token(creds.credentials) if creds else None
    if not parsed:
        raise AuthError("Потрібен вхід")
    # Перевіряє, що користувач існує, активний і що версія токена актуальна (див. security.create_access_token).
    return await auth_service.user_from_token(db, parsed.user_id, parsed.token_version)


CurrentUser = Annotated[User, Depends(current_user)]
