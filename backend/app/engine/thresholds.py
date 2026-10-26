"""Оцінювач порогів (ТЗ розд. 7.1): чисті функції без БД і мережі.

step() отримує вже агреговане значення й стан ряду, а повертає новий стан і дії для сервісу.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

Severity = Literal["warning", "critical"]
Direction = Literal["above", "below", "equals"]
AGG_SQL = {"avg": "avg(value)", "max": "max(value)", "min": "min(value)", "delta": "(max(value) - min(value))"}  # агрегати за вікно в SQL
HYSTERESIS = 0.05  # закриття після повернення за поріг ще на 5 % (ТЗ 7.1)


@dataclass(frozen=True)
class Threshold:
    metric: str
    agg: Literal["last", "avg", "max", "delta"] = "last"  # delta – приріст лічильника за вікно (max − min)
    window_s: int = 0
    warn: float | None = None
    crit: float | None = None
    direction: Direction = "above"
    duration_s: int = 60


@dataclass(frozen=True)
class State:
    breach_since: datetime | None = None   # з якого моменту триває порушення
    incident: Severity | None = None       # рівень відкритого інциденту
    calm_since: datetime | None = None     # з якого моменту значення в нормі (з гістерезисом)


@dataclass(frozen=True)
class Open:
    severity: Severity
    value: float
    first_breach_at: datetime


@dataclass(frozen=True)
class Escalate:
    severity: Severity
    value: float


@dataclass(frozen=True)
class Deescalate:
    severity: Severity
    value: float


@dataclass(frozen=True)
class Resolve:
    value: float


Action = Open | Escalate | Deescalate | Resolve


def _beyond(value: float, limit: float, direction: Direction) -> bool:
    if direction == "above":
        return value > limit
    if direction == "below":
        return value < limit
    return value == limit


def classify(value: float, th: Threshold) -> Severity | None:
    if th.crit is not None and _beyond(value, th.crit, th.direction):
        return "critical"
    if th.warn is not None and _beyond(value, th.warn, th.direction):
        return "warning"
    return None


def _clear(value: float, limit: float, th: Threshold) -> bool:
    """Значення повернулося за поріг із запасом (гістерезис); бінарні метрики запасу не мають."""
    if th.direction == "equals":
        return value != limit
    if th.direction == "above":
        return value < limit * (1 - HYSTERESIS)
    return value > limit * (1 + HYSTERESIS)


def _lowest(th: Threshold) -> float:
    """Найнижчий заданий поріг (warn, а якщо його немає – crit): від нього рахується гістерезис."""
    return th.warn if th.warn is not None else th.crit


def step(state: State, th: Threshold, value: float, ts: datetime) -> tuple[State, list[Action]]:
    level = classify(value, th)
    dur = timedelta(seconds=th.duration_s)

    if state.incident is None:
        if level is None:
            return State(), []
        since = state.breach_since or ts
        if ts - since >= dur:
            return State(breach_since=since, incident=level), [Open(level, value, since)]
        return State(breach_since=since), []

    # інцидент уже відкритий
    if level == "critical" and state.incident == "warning":
        return replace(state, incident="critical", calm_since=None), [Escalate("critical", value)]
    if level is not None:
        if level == "warning" and state.incident == "critical" and th.crit is not None \
                and _clear(value, th.crit, th) and th.direction != "equals":
            return replace(state, incident="warning", calm_since=None), [Deescalate("warning", value)]
        return replace(state, calm_since=None), []

    # значення в нормі: закриваємо лише після гістерезису й `duration_s` спокою
    if not _clear(value, _lowest(th), th):
        return replace(state, calm_since=None), []
    calm = state.calm_since or ts
    if ts - calm >= dur:
        return State(), [Resolve(value)]
    return replace(state, calm_since=calm), []
