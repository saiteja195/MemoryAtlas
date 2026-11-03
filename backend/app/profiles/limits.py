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


class Budget:
    """How many times an address and a profile may call the model per hour. Open sign-up must not be a way to spend the
    owner's model key. A demo profile has a public passcode, so only the address limit applies to it."""

    def __init__(self, per_profile: RateLimiter | None = None, per_ip: RateLimiter | None = None):
        self.per_profile = per_profile or RateLimiter(100, 3600)
        self.per_ip = per_ip or RateLimiter(300, 3600)

    def check(self, profile_id: str, demo: bool, ip: str) -> float:
        """0 when allowed, else the seconds to wait."""
        if not demo and not self.per_profile.allow(profile_id):
            return max(1.0, self.per_profile.retry_after(profile_id))
        if not self.per_ip.allow(ip):
            return max(1.0, self.per_ip.retry_after(ip))
        return 0.0
