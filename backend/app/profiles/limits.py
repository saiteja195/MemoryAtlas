"""A small in-memory sliding-window limiter, keyed by client address."""
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)           # forget quiet keys so the table cannot grow forever
        return hits

    def allow(self, key: str) -> bool:
        """Record the attempt only when it is allowed; blocked attempts do not extend the window."""
        with self._lock:
            now = self.clock()
            hits = self._trim(key, now)
            if len(hits) >= self.limit:
                return False
            self._hits[key].append(now)
            return True

    def retry_after(self, key: str) -> float:
        with self._lock:
            now = self.clock()
            hits = self._trim(key, now)
            if len(hits) < self.limit:
                return 0.0
            return max(0.0, hits[0] + self.window - now)
