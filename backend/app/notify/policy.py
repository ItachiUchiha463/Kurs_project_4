"""Кому і що надсилати (ТЗ розділ 9).

Окремий файл із чистою функцією-рішенням: легко тестується й змінюється, не торкаючись доставки.
"""

# Числове порівняння рівнів: критичний «більший» за попередження.
SEVERITY_RANK = {"warning": 0, "critical": 1}


def should_notify(*, chat_id: int | None, min_severity: str, kind: str, severity: str, had_open_notification: bool) -> bool:
    """kind: opened | escalated | deescalated | resolved.

    «Відновлено» надсилаємо лише тим, кому раніше надсилали про сам інцидент, щоб у чаті була пара «впало → піднялось».

    Правила рішення, по порядку:
      1. немає прив'язаного Telegram-чату – нікуди слати;
      2. зниження рівня й придушені інциденти – не сповіщаємо (шум без користі);
      3. рівень інциденту нижчий за мінімальний, який обрав користувач (профіль: «усі» чи «лише критичні») – не слати;
      4. «відновлено» – лише якщо раніше надсилали про відкриття;
      5. решту (відкрито, ескалація) – слати.
    """
    if chat_id is None or kind in ("deescalated", "suppressed"):
        return False
    if SEVERITY_RANK[severity] < SEVERITY_RANK[min_severity]:
        return False
    if kind == "resolved":
        return had_open_notification
    return True
