"""Прості обмеження частоти в пам'яті процесу (ТЗ розд. 6).

shortcut: стан живе в одному процесі (рівно один uvicorn-процес, ТЗ розд. 3); при кількох процесах – винести в БД чи Redis.
"""
import time
from collections import deque

_MAX_KEYS = 10_000  # ключі (IP, email) від зловмисника не повинні роздувати пам'ять


class SlidingWindow:
    """Не більше `limit` подій за `window_s` секунд на ключ."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float | None = None) -> bool:
        """True – подію допущено, False – ліміт вичерпано."""
        now = time.monotonic() if now is None else now
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > _MAX_KEYS:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_s}
        return True

    def reset(self) -> None:
        self._hits.clear()


class FailureLock:
    """`limit` невдач поспіль – ключ блокується на `lock_s` секунд; успіх скидає лічильник."""

    def __init__(self, limit: int, lock_s: float):
        self.limit, self.lock_s = limit, lock_s
        self._state: dict[str, tuple[int, float]] = {}  # ключ → (невдач поспіль, до коли заблоковано)

    def locked(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self._state.get(key, (0, 0.0))[1] > now

    def fail(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        count, _ = self._state.get(key, (0, 0.0))
        count += 1
        self._state[key] = (0, now + self.lock_s) if count >= self.limit else (count, 0.0)
        if len(self._state) > _MAX_KEYS:
            self._state = {k: v for k, v in self._state.items() if v[1] > now or v[0] > 0}

    def ok(self, key: str) -> None:
        self._state.pop(key, None)

    def reset(self) -> None:
        self._state.clear()
