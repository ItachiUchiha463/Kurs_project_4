"""REST-маршрути об'єктів моніторингу й приймання метрик від агента.

Це «шар представлення»: тут лише розбір запиту, виклик сервісу й формування відповіді. Бізнес-логіка живе
в services/targets.py і services/ingest.py. Параметри `user: CurrentUser` і `db: DbDep` підставляє FastAPI
(app/deps.py): перший автентифікує запит за JWT, другий дає сесію БД.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status

from app.deps import CurrentUser, DbDep
from app.errors import AuthError
from app.schemas.targets import (
    AgentTokenOut, HiddenIn, IngestBatch, IngestOut, IngestRecord, Point, TargetCreate, TargetCreated, TargetOut,
)
from app.services import ingest as ingest_service
from app.services import targets as service

router = APIRouter(tags=["targets"])


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(user: CurrentUser, db: DbDep):
    """Усі об'єкти користувача з останніми значеннями метрик (для дашборда)."""
    return await service.list_targets(db, user)


@router.post("/targets", response_model=TargetCreated, status_code=status.HTTP_201_CREATED)
async def create_target(data: TargetCreate, user: CurrentUser, db: DbDep, response: Response):
    """Створює сервер або сервіс. Для сервера у відповіді є токен агента (показується один раз)."""
    created = await service.create_target(db, user, data)
    response.headers["Location"] = f"/api/targets/{created.id}"  # REST-практика: адреса створеного ресурсу
    return created


@router.get("/targets/{target_id}", response_model=TargetOut)
async def get_target(target_id: int, user: CurrentUser, db: DbDep):
    """Один об'єкт. Чужий об'єкт дає 404, а не 403 (щоб не видати, що він існує)."""
    return await service.get_target(db, user, target_id)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(target_id: int, user: CurrentUser, db: DbDep):
    await service.delete_target(db, user, target_id)


@router.get("/targets/{target_id}/children", response_model=list[TargetOut])
async def children(target_id: int, user: CurrentUser, db: DbDep):
    """Контейнери й бази даних сервера (виявлені агентом)."""
    return await service.list_children(db, user, target_id)


@router.put("/targets/{target_id}/hidden", response_model=TargetOut)
async def set_hidden(target_id: int, data: HiddenIn, user: CurrentUser, db: DbDep):
    return await service.set_hidden(db, user, target_id, data.hidden)


@router.post("/targets/{target_id}/agent-token", response_model=AgentTokenOut)
async def agent_token(target_id: int, user: CurrentUser, db: DbDep):
    """Новий токен агента (старий перестає діяти)."""
    return AgentTokenOut(agent_token=await service.rotate_token(db, user, target_id))


@router.get("/targets/{target_id}/metrics", response_model=list[Point])
async def target_metrics(target_id: int, user: CurrentUser, db: DbDep, name: str, instance: str = "",
                         start: Annotated[datetime | None, Query(alias="from")] = None,
                         end: Annotated[datetime | None, Query(alias="to")] = None):
    """Ряд метрики для графіка. Без параметрів from/to – остання година."""
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=1)
    return await service.metric_series(db, user, target_id, name, instance, start, end)


@router.post("/ingest", response_model=IngestOut)
async def ingest(payload: IngestBatch | list[IngestRecord], db: DbDep,
                 authorization: Annotated[str | None, Header()] = None,
                 x_agent_time: Annotated[datetime | None, Header()] = None,
                 x_agent_version: Annotated[str | None, Header()] = None,
                 x_agent_interval: Annotated[int | None, Header()] = None):
    """Приймання метрик від АГЕНТА. Автентифікація тут не JWT користувача, а токен агента в заголовку Authorization.

    Тіло може бути або списком записів (проста форма), або об'єктом із записами й знімком контейнерів/баз.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Потрібен токен агента")
    batch = payload if isinstance(payload, IngestBatch) else IngestBatch(records=payload)
    return await ingest_service.ingest(db, token, batch, x_agent_time, x_agent_version, x_agent_interval)
