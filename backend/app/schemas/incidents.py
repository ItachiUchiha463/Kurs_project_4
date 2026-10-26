from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_id: int
    target_name: str = ""
    metric: str
    instance: str
    severity: str
    status: str
    value_at_open: float | None
    first_breach_at: datetime | None
    started_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolve_comment: str | None
    suppressed_by: int | None = None
    suppressed_count: int = 0  # скільки дочірніх інцидентів придушено цим (ТЗ 7.1.1)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str
    value: float | None
    ts: datetime
    note: str | None


class EvidenceItem(BaseModel):
    ok: bool
    text: str
    value: str


class DiagnosisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cause: str
    recommendation: str
    matched_ratio: float
    evidence: list[EvidenceItem]
    alternatives: list[dict] = []


class IncidentDetail(IncidentOut):
    events: list[EventOut]
    diagnosis: DiagnosisOut | None = None
    related: list[IncidentOut] = []  # придушені дочірні інциденти


class ResolveIn(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)
