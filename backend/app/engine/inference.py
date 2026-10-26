"""Механізм логічного виведення (ТЗ розд. 8): продукційні правила «ЯКЩО умови – ТО причина».

Чисті функції: на вході правила й факти (агрегати метрик), на виході висновок із доказами.
"""
from dataclasses import dataclass, field
from typing import Literal

Scope = Literal["self", "host"]
OPS = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b, "==": lambda a, b: a == b,
}
PARTIAL_MIN = 0.5  # правила з такою часткою виконаних умов показуються як «можливі причини»

METRIC_LABELS = {
    "cpu_usage": "CPU", "ram_usage": "RAM", "swap_usage": "Swap", "disk_usage": "Диск",
    "load_per_core": "Навантаження на ядро", "response_ms": "Час відповіді", "available": "Доступність",
    "agent_alive": "Агент працює", "status_code": "HTTP-код", "net_total": "Мережа",
    "ping_available": "Ping", "packet_loss": "Втрати пакетів",
    "container_running": "Контейнер працює", "container_oom_killed": "Нестача пам'яті (OOM)", "container_exit_code": "Код виходу",
    "container_health": "Healthcheck", "container_restarts": "Перезапуски", "container_cpu": "CPU контейнера", "container_mem": "RAM контейнера",
}
UNITS = {"cpu_usage": "%", "ram_usage": "%", "swap_usage": "%", "disk_usage": "%", "response_ms": "мс", "net_total": "КБ/с", "packet_loss": "%", "container_cpu": "%", "container_mem": "%"}
AGG_TEXT = {"avg": "середнє", "max": "максимум", "min": "мінімум", "delta": "приріст"}


@dataclass(frozen=True)
class Condition:
    scope: Scope
    metric: str
    op: str
    value: float
    agg: str = "last"
    window_s: int = 0
    instance: str | None = None  # None – ряд без instance; "any" – найгірший серед рядів; "same" – як в інциденті

    @property
    def fact_key(self) -> tuple:
        return (self.scope, self.metric, self.agg, self.window_s, self.instance)


@dataclass(frozen=True)
class Rule:
    id: int | None
    name: str
    cause: str
    recommendation: str
    applies_to: tuple[str, ...]
    conditions: tuple[Condition, ...]
    priority: int = 0
    own: bool = False  # власне правило користувача: вище за базове з тією ж кількістю умов


@dataclass(frozen=True)
class Evidence:
    ok: bool
    text: str
    value: str


@dataclass(frozen=True)
class Match:
    rule: Rule
    ratio: float
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnosis:
    primary: Match | None
    alternatives: list[Match]


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _describe(c: Condition, names: dict[str, str]) -> str:
    who = names[c.scope]
    label = METRIC_LABELS.get(c.metric, c.metric)
    window = f", {AGG_TEXT[c.agg]} за {c.window_s // 60} хв" if c.agg != "last" and c.window_s else ""
    return f"{label} {who}{window}"


def evaluate(rule: Rule, facts: dict[tuple, float | None], names: dict[str, str]) -> Match:
    evidence, ok_count = [], 0
    for c in rule.conditions:
        actual = facts.get(c.fact_key)
        unit = f" {UNITS[c.metric]}" if c.metric in UNITS else ""
        if actual is None:
            evidence.append(Evidence(False, _describe(c, names), "немає даних"))
            continue
        ok = OPS[c.op](actual, c.value)
        ok_count += ok
        evidence.append(Evidence(ok, _describe(c, names), f"{_num(actual)}{unit} {c.op} {_num(c.value)}{unit}"))
    return Match(rule, ok_count / len(rule.conditions) if rule.conditions else 0.0, evidence)


def diagnose(rules: list[Rule], facts: dict[tuple, float | None], names: dict[str, str], target_type: str) -> Diagnosis:
    """Правило з усіма виконаними умовами – причина; конкретніше (більше умов) вище, далі власні, далі priority."""
    matches = [evaluate(r, facts, names) for r in rules if target_type in r.applies_to]
    full = sorted((m for m in matches if m.ratio == 1.0),
                  key=lambda m: (len(m.rule.conditions), m.rule.own, m.rule.priority), reverse=True)
    primary = full[0] if full else None
    partial = sorted((m for m in matches if PARTIAL_MIN <= m.ratio < 1.0), key=lambda m: m.ratio, reverse=True)
    return Diagnosis(primary, [m for m in full[1:]] + partial)
