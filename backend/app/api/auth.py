from fastapi import APIRouter, Depends, Request, Response, status

from app.config import settings
from app.deps import CurrentUser, DbDep
from app.errors import TooManyRequests
from app.ratelimit import SlidingWindow
from app.schemas.auth import ForgotIn, LoginIn, RegisterIn, ResetIn, TokenOut, UserOut
from app.schemas.auth import ProfileIn, TelegramLinkOut
from app.services import auth, telegram_link

router = APIRouter(tags=["auth"])

register_limiter = SlidingWindow(settings.rate_register_per_min, 60)
login_limiter = SlidingWindow(settings.rate_login_per_min, 60)
reset_limiter = SlidingWindow(settings.rate_reset_per_min, 60)


def _limit(limiter: SlidingWindow):
    async def check(request: Request):
        # за Caddy справжню адресу дає uvicorn --proxy-headers (див. Dockerfile)
        if not limiter.hit(request.client.host if request.client else "unknown"):
            raise TooManyRequests("Забагато спроб. Спробуйте за хвилину")
    return Depends(check)


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             dependencies=[_limit(register_limiter)])
async def register(data: RegisterIn, db: DbDep):
    return TokenOut(access_token=await auth.register(db, data))


@router.post("/auth/login", response_model=TokenOut, dependencies=[_limit(login_limiter)])
async def login(data: LoginIn, db: DbDep, request: Request):
    return TokenOut(access_token=await auth.login(db, data, request.client.host if request.client else ""))


@router.post("/auth/forgot", status_code=status.HTTP_202_ACCEPTED, dependencies=[_limit(reset_limiter)])
async def forgot(data: ForgotIn, db: DbDep):
    await auth.forgot_password(db, data.email)
    return {"message": "Якщо до облікового запису прив'язано Telegram, посилання для скидання надіслано туди"}


@router.post("/auth/reset", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_limit(reset_limiter)])
async def reset(data: ResetIn, db: DbDep):
    await auth.reset_password(db, data.token, data.password)


@router.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser):
    await auth.logout_all(user)


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
