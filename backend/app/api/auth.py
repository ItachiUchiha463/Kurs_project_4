from fastapi import APIRouter, Response, status

from app.deps import CurrentUser, DbDep
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.schemas.auth import ProfileIn, TelegramLinkOut
from app.services import auth, telegram_link

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


@router.patch("/me", response_model=UserOut)
async def update_me(data: ProfileIn, user: CurrentUser):
    user.notify_min_severity = data.notify_min_severity
    return await me(user)


@router.post("/me/telegram", response_model=TelegramLinkOut)
async def telegram_connect(user: CurrentUser, db: DbDep):
    return await telegram_link.create_link(db, user)


@router.delete("/me/telegram", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_disconnect(user: CurrentUser):
    telegram_link.unlink(user)


@router.post("/me/telegram/test", status_code=status.HTTP_202_ACCEPTED)
async def telegram_test(user: CurrentUser, db: DbDep):
    telegram_link.send_test(db, user)
    return Response(status_code=status.HTTP_202_ACCEPTED)
