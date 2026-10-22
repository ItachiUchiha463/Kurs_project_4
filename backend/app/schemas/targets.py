from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["server", "service"]
    address: str | None = Field(default=None, max_length=500)
    interval_s: int = Field(default=30, ge=15, le=3600)
    expected_status: str = "200-399"

    @model_validator(mode="after")
    def _address_for_service(self):
        # сервер працює через агента й адреси не потребує; сервіс перевіряється за URL
        if self.type == "service" and not (self.address and self.address.startswith(("http://", "https://"))):
            raise ValueError("Для сервісу вкажіть адресу, що починається з http:// або https://")
        return self


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # agent_token_hash у схемі відсутній – у відповідь не потрапить
    id: int
    name: str
    type: str
    check_type: str
    address: str | None
    interval_s: int
    status: str
    last_seen: datetime | None
    agent_version: str | None = None
    clock_offset_s: float | None = None
    latest: dict[str, float] = {}


class TargetCreated(TargetOut):
    agent_token: str | None = None  # показується один раз


class AgentTokenOut(BaseModel):
    agent_token: str


class IngestRecord(BaseModel):
    host: str
    metric: str
    value: float
    instance: str = ""
    unit: str | None = None
    timestamp: datetime
    target: str | None = None


class IngestRejected(BaseModel):
    index: int
    reason: str


class IngestOut(BaseModel):
    accepted: int
    rejected: list[IngestRejected]


class Point(BaseModel):
    ts: datetime
    value: float
