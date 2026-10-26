from fastapi import APIRouter, Response, status

from app.deps import CurrentUser, DbDep
from app.schemas.thresholds import ThresholdIn, ThresholdOut
from app.services import thresholds as service

router = APIRouter(tags=["thresholds"])


@router.get("/thresholds", response_model=list[ThresholdOut])
async def list_thresholds(user: CurrentUser, db: DbDep, target_id: int | None = None):
    return await service.list_effective(db, user, target_id)


@router.put("/thresholds", status_code=status.HTTP_204_NO_CONTENT)
async def save_threshold(data: ThresholdIn, user: CurrentUser, db: DbDep):
    await service.save(db, user, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/thresholds", status_code=status.HTTP_204_NO_CONTENT)
async def reset_threshold(metric: str, user: CurrentUser, db: DbDep, target_id: int | None = None):
    await service.reset(db, user, metric, target_id)
