from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings
from app.errors import install_handlers
from app.logging import RequestLogMiddleware, setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Vigil", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["*"], allow_headers=["*"])
    install_handlers(app)
    app.include_router(router, prefix="/api")
    return app


app = create_app()
