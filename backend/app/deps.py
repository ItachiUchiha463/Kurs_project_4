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
_bearer = HTTPBearer(auto_error=False)


async def current_user(
    db: DbDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None
) -> User:
    parsed = decode_access_token(creds.credentials) if creds else None
    if not parsed:
        raise AuthError("Потрібен вхід")
    return await auth_service.user_from_token(db, parsed.user_id, parsed.token_version)


CurrentUser = Annotated[User, Depends(current_user)]
