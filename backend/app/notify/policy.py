"""Кому і що надсилати (ТЗ розділ 9)."""

SEVERITY_RANK = {"warning": 0, "critical": 1}


def should_notify(*, chat_id: int | None, min_severity: str, kind: str, severity: str, had_open_notification: bool) -> bool:
    """kind: opened | escalated | deescalated | resolved.

    «Відновлено» надсилаємо лише тим, кому раніше надсилали про сам інцидент, щоб у чаті була пара «впало → піднялось».
    """
    if chat_id is None or kind in ("deescalated", "suppressed"):
        return False
    if SEVERITY_RANK[severity] < SEVERITY_RANK[min_severity]:
        return False
    if kind == "resolved":
        return had_open_notification
    return True
