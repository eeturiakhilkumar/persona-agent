"""Tiny in-memory sliding-window rate limiter (per process; resets on restart)."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key) -> bool:
        """Record a hit for `key` and return True, or return False if the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:  # keep memory bounded under key churn
                self._purge(now)
            hits = self._hits[str(key)]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _purge(self, now: float):
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
            del self._hits[key]
