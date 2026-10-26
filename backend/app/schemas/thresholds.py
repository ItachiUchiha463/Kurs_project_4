from typing import Literal

from pydantic import BaseModel, Field


class ThresholdIn(BaseModel):
    metric: str = Field(max_length=100)
    target_id: int | None = None  # None – шаблон для всіх об'єктів користувача
    warn: float | None = Field(default=None, ge=0, le=1_000_000_000)
    crit: float | None = Field(default=None, ge=0, le=1_000_000_000)
    duration_s: int = Field(ge=0, le=3600)


class ThresholdOut(BaseModel):
    metric: str
    agg: str
    window_s: int
    warn: float | None
    crit: float | None
    direction: str
    duration_s: int
    source: Literal["default", "template", "target"]
    levels_editable: bool  # false для бінарних метрик (доступність): змінюється лише тривалість
