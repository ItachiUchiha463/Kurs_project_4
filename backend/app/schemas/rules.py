from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.engine.defaults import DEFAULT_THRESHOLDS
from app.metric_catalog import KNOWN_METRICS

TargetType = Literal["server", "service", "container", "database"]


class ConditionModel(BaseModel):
    """Одна умова правила (ТЗ 8.1); усі умови правила поєднуються через «І»."""
    scope: Literal["self", "host", "siblings"]
    metric: str
    op: Literal[">", ">=", "<", "<=", "=="]
    value: float = Field(ge=-1_000_000_000, le=1_000_000_000)
    agg: Literal["last", "avg", "max", "min", "delta"] = "last"
    window_s: int = Field(default=0, ge=0, le=3600)
    instance: str | None = Field(default=None, max_length=100)  # None, "any", "same" або конкретне значення
    sibling_type: Literal["container", "database", "service"] | None = None
    match: Literal["any", "all"] = "any"

    @field_validator("metric")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in KNOWN_METRICS:
            raise ValueError(f"Невідома метрика «{v}»")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        if self.agg != "last" and self.window_s <= 0:
            raise ValueError("Для агрегації за вікном вкажіть вікно в секундах")
        if self.scope == "siblings" and self.sibling_type is None:
            raise ValueError("Для сусідніх об'єктів вкажіть їхній тип")
        return self


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cause: str = Field(min_length=1, max_length=200)
    recommendation: str = Field(min_length=1, max_length=1000)
    applies_to: list[TargetType] = Field(min_length=1, max_length=4)
    conditions: list[ConditionModel] = Field(min_length=1, max_length=6)
    priority: int = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def _completeness(self):
        # «правило повноти» (ТЗ 7.3): перша умова – симптом самого об'єкта, для якого є типовий поріг, інакше правило ніколи не розглядається
        first = self.conditions[0]
        if first.scope != "self" or first.metric not in DEFAULT_THRESHOLDS:
            raise ValueError("Перша умова має описувати сам об'єкт (scope = self) і метрику, для якої є поріг")
        return self


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    cause: str
    recommendation: str
    applies_to: list[str]
    conditions: list[dict]
    priority: int
    enabled: bool
    own: bool


class EnabledIn(BaseModel):
    enabled: bool


class RuleTestOut(BaseModel):
    ratio: float
    matched: bool
    evidence: list[dict]
