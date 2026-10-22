from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbDep
from app.schemas.incidents import IncidentDetail, IncidentOut, ResolveIn
from app.services import incidents as service

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=list[IncidentOut])
async def list_incidents(user: CurrentUser, db: DbDep,
                         status: Literal["active", "open", "acknowledged", "resolved"] | None = None,
                         target_id: int | None = None, severity: Literal["warning", "critical"] | None = None,
                         cursor: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return await service.list_incidents(db, user, status, target_id, severity, cursor, limit)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: int, user: CurrentUser, db: DbDep):
    return await service.get_incident(db, user, incident_id)


@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentOut)
async def acknowledge(incident_id: int, user: CurrentUser, db: DbDep):
    return await service.acknowledge(db, user, incident_id)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve(incident_id: int, data: ResolveIn, user: CurrentUser, db: DbDep):
    return await service.resolve(db, user, incident_id, data.comment)
