from fastapi import APIRouter, status

from app.deps import CurrentUser, DbDep
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services import auth

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, db: DbDep):
    return TokenOut(access_token=await auth.register(db, data))


@router.post("/auth/login", response_model=TokenOut)
async def login(data: LoginIn, db: DbDep):
    return TokenOut(access_token=await auth.login(db, data))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return UserOut(id=user.id, email=user.email, full_name=user.full_name,
                   telegram_linked=user.telegram_chat_id is not None,
                   notify_min_severity=user.notify_min_severity)
