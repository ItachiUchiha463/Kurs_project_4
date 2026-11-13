"""Точка входу серверної частини: створення застосунку FastAPI.

Запускається командою `uvicorn app.main:app` (див. backend/Dockerfile).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.background import Background
from app.config import settings
from app.errors import install_handlers
from app.logging import RequestLogMiddleware, setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Життєвий цикл: код до `yield` виконується при старті, після `yield` – при зупинці застосунку."""
    setup_logging(settings.log_level)
    bg = Background()
    await bg.start()  # фонові задачі: перевірки, контроль агентів, сповіщення, Telegram-бот
    yield
    await bg.stop()


def create_app() -> FastAPI:
    """Збирає застосунок: проміжні шари, обробники помилок, маршрути."""
    # Документація API генерується автоматично за типами в схемах: /api/docs.
    app = FastAPI(title="Vigil", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(RequestLogMiddleware)  # журнал кожного запиту (JSON): id запиту, час, код відповіді
    # CORS: з яких адрес браузер може звертатись до API (у проді фронтенд і API на одному домені, тож це запас).
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["*"], allow_headers=["*"])
    install_handlers(app)  # єдиний формат помилок (app/errors.py)
    app.include_router(router, prefix="/api")  # усі маршрути під /api
    return app


app = create_app()
