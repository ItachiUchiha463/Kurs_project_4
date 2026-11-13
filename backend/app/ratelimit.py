"""Прості обмеження частоти в пам'яті процесу (ТЗ розд. 6).

shortcut: стан живе в одному процесі (рівно один uvicorn-процес, ТЗ розд. 3); при кількох процесах – винести в БД чи Redis.

Два механізми, обидва потрібні для захисту від перебору й спаму:
  SlidingWindow – «не більше N подій за T секунд» (наприклад, 5 реєстрацій за хвилину з однієї IP);
  FailureLock   – «N невдач поспіль -> блокування на певний час» (наприклад, 10 неправильних паролів -> 15 хвилин).
"""
import time
from collections import deque

_MAX_KEYS = 10_000  # ключі (IP, email) від зловмисника не повинні роздувати пам'ять


class SlidingWindow:
    """Не більше `limit` подій за `window_s` секунд на ключ."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque[float]] = {}  # ключ -> час останніх подій

    def hit(self, key: str, now: float | None = None) -> bool:
        """True – подію допущено, False – ліміт вичерпано."""
        now = time.monotonic() if now is None else now
        q = self._hits.setdefault(key, deque())
        # «Ковзне вікно»: викидаємо події, що вже вийшли за межі вікна.
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > _MAX_KEYS:
            # Захист пам'яті: залишаємо лише ключі з актуальними подіями.
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_s}
        return True

    def reset(self) -> None:
        """Очищає всі лічильники (використовується в тестах)."""
        self._hits.clear()


class FailureLock:
    """`limit` невдач поспіль – ключ блокується на `lock_s` секунд; успіх скидає лічильник."""

    def __init__(self, limit: int, lock_s: float):
        self.limit, self.lock_s = limit, lock_s
        self._state: dict[str, tuple[int, float]] = {}  # ключ → (невдач поспіль, до коли заблоковано)

    def locked(self, key: str, now: float | None = None) -> bool:
        """Чи заблоковано ключ зараз."""
        now = time.monotonic() if now is None else now
        return self._state.get(key, (0, 0.0))[1] > now

    def fail(self, key: str, now: float | None = None) -> None:
        """Реєструє невдалу спробу; якщо ліміт досягнуто, блокує ключ і скидає лічильник."""
        now = time.monotonic() if now is None else now
        count, _ = self._state.get(key, (0, 0.0))
        count += 1
        self._state[key] = (0, now + self.lock_s) if count >= self.limit else (count, 0.0)
        if len(self._state) > _MAX_KEYS:
            self._state = {k: v for k, v in self._state.items() if v[1] > now or v[0] > 0}

    def ok(self, key: str) -> None:
        """Успішна спроба: лічильник невдач скидається."""
        self._state.pop(key, None)

    def reset(self) -> None:
        """Очищає всі стани (використовується в тестах)."""
        self._state.clear()
