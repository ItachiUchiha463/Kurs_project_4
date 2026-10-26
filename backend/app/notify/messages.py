"""Тексти сповіщень Telegram (ТЗ 9.1). Чисті функції, HTML-розмітка."""
from datetime import datetime
from html import escape as _escape
from zoneinfo import ZoneInfo

from app.engine.defaults import DEFAULT_THRESHOLDS
from app.engine.inference import METRIC_LABELS, UNITS


def escape(text: str) -> str:
    return _escape(text, quote=False)  # Telegram HTML потребує лише <, > та &; апостроф лишаємо як є


KYIV = ZoneInfo("Europe/Kyiv")
ICON = {"critical": "🔴", "warning": "🟡"}
TITLE = {"critical": "КРИТИЧНО", "warning": "ПОПЕРЕДЖЕННЯ"}


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def describe(metric: str, instance: str, value: float) -> str:
    if metric == "available":
        return "Сервіс недоступний"
    if metric == "ping_available":
        return "Сервер не відповідає на ping"
    if metric == "agent_alive":
        return "Агент не надсилає дані"
    unit = UNITS.get(metric, "")
    inst = f" {instance}" if instance else ""
    return f"{METRIC_LABELS.get(metric, metric)}{inst} {num(value)}{' ' + unit if unit else ''}"


def threshold_text(metric: str, severity: str) -> str:
    th = DEFAULT_THRESHOLDS.get(metric)
    limit = th and (th.crit if severity == "critical" else th.warn)
    if limit is None or th.direction == "equals":
        return ""
    unit = UNITS.get(metric, "")
    return f" (поріг {num(limit)}{' ' + unit if unit else ''})"


def local_time(ts: datetime) -> str:
    return ts.astimezone(KYIV).strftime("%H:%M")


def render(kind: str, *, target: str = "", metric: str = "", instance: str = "", severity: str = "critical", value: float = 0.0,
           ts: datetime | None = None, cause: str | None = None, minutes: int | None = None, dependents: int = 0) -> str:
    name = escape(target)
    if kind == "test":
        return "✅ <b>Vigil</b>: тестове повідомлення. Сповіщення працюють."
    if kind == "resolved":
        text = f"🟢 <b>Відновлено</b> · {name} · {escape(describe(metric, instance, value)) if metric not in ('available', 'agent_alive', 'ping_available') else 'працює'}"
        return text + (f" · тривало {minutes} хв" if minutes is not None else "")
    title = TITLE[severity] + (" (підвищено)" if kind == "escalated" else "")
    text = (f"{ICON[severity]} <b>{title}</b> · {name} · {escape(describe(metric, instance, value))}"
            f"{threshold_text(metric, severity)} · {local_time(ts) if ts else ''}")
    if dependents:
        text += f"\nЗалежних об’єктів: {dependents}"
    if cause:
        text += f"\nЙмовірна причина: {escape(cause)}"
    return text
