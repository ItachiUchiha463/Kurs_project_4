from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.deps import CurrentUser, DbDep
from app.schemas.reports import ReportOut
from app.services import reports as service

router = APIRouter(tags=["reports"])


@router.get("/reports", response_model=ReportOut)
async def report(user: CurrentUser, db: DbDep,
                 start: Annotated[datetime | None, Query(alias="from")] = None,
                 end: Annotated[datetime | None, Query(alias="to")] = None,
                 format: Literal["json", "csv"] = "json"):
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=7)
    result = await service.build(db, user, start, end)
    if format == "csv":
        body = "﻿" + service.to_csv(result)  # BOM, щоб Excel розпізнав UTF-8
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="vigil-report-{start:%Y%m%d}-{end:%Y%m%d}.csv"'})
    return result
