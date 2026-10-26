from datetime import datetime

from pydantic import BaseModel


class MetricStat(BaseModel):
    avg: float
    max: float


class ReportRow(BaseModel):
    target_id: int
    name: str
    type: str
    availability_pct: float
    incidents: int
    warning: int
    critical: int
    mean_detect_s: float | None
    mean_recover_s: float | None
    metrics: dict[str, MetricStat]


class TopCause(BaseModel):
    cause: str
    count: int


class ReportOut(BaseModel):
    start: datetime
    end: datetime
    incidents: int
    critical: int
    rows: list[ReportRow]
    top_causes: list[TopCause]
