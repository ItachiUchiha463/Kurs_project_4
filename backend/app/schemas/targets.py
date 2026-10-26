from datetime import datetime
from typing import Literal

import httpx
from app.addresses import split_host_port
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["server", "service"]
    address: str | None = Field(default=None, max_length=500)
    interval_s: int = Field(default=30, ge=15, le=3600)
    expected_status: str = "200-399"
    host_id: int | None = None  # сервер, на якому працює сервіс (для правил із `host`)
    check_type: Literal["http", "tcp", "ping"] = "http"  # лише для сервісу
    ping_enabled: bool = False  # лише для сервера: планувальник пінгує його адресу

    @model_validator(mode="after")
    def _address(self):
        # сервер працює через агента; адреса потрібна лише для ping. Сервіс перевіряється за адресою свого типу
        if self.type == "server":
            if self.ping_enabled and not self.address:
                raise ValueError("Для ping вкажіть адресу сервера")
            return self
        if self.check_type == "http":
            if not (self.address and self.address.startswith(("http://", "https://"))):
                raise ValueError("Для сервісу вкажіть адресу, що починається з http:// або https://")
            if httpx.URL(self.address).userinfo:
                raise ValueError("Адреса не повинна містити логін і пароль")
        elif self.check_type == "tcp":
            split_host_port(self.address or "")
        elif not self.address or "/" in self.address or ":" in self.address:
            raise ValueError("Для ping вкажіть лише ім'я хоста або IP-адресу")
        return self


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # agent_token_hash у схемі відсутній – у відповідь не потрапить
    id: int
    name: str
    type: str
    check_type: str
    address: str | None
    host_id: int | None = None
    ping_enabled: bool = False
    source: str = "manual"
    hidden: bool = False
    interval_s: int
    status: str
    last_seen: datetime | None
    agent_version: str | None = None
    clock_offset_s: float | None = None
    latest: dict[str, float] = {}


class TargetCreated(TargetOut):
    agent_token: str | None = None  # показується один раз


class HiddenIn(BaseModel):
    hidden: bool


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


class ContainerInfo(BaseModel):
    """Контейнер, виявлений агентом на сервері (ТЗ 5.3)."""
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    image: str = Field(default="", max_length=200)
    state: str = Field(default="", max_length=30)


class DatabaseInfo(BaseModel):
    """База даних із agent.toml (ТЗ 5.4); id – ім'я з конфігурації, за ним агент позначає записи («postgres:<id>»)."""
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    engine: Literal["postgres"] = "postgres"


class IngestBatch(BaseModel):
    records: list[IngestRecord]
    containers: list[ContainerInfo] = []
    databases: list[DatabaseInfo] = []


class IngestRejected(BaseModel):
    index: int
    reason: str


class IngestOut(BaseModel):
    accepted: int
    rejected: list[IngestRejected]


class Point(BaseModel):
    ts: datetime
    value: float
