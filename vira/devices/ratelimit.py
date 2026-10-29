"""Small in-process token-bucket rate limiter (per device / per user / per key).

Good enough for a single API process.  For multi-process deployments replace
the backing store (Redis, gateway) behind the same ``allow`` interface.
"""
import threading
import time
from typing import Dict, Tuple


class RateLimiter:
    def __init__(self, per_minute: int, burst: int = 0, clock=time.monotonic):
        self._rate = max(1, per_minute) / 60.0
        self._burst = float(burst or max(1, per_minute))
        self._clock = clock
        self._state: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> Tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            tokens, last = self._state.get(key, (self._burst, now))
            tokens = min(self._burst, tokens + (now - last) * self._rate)
            if cost > self._burst:
                cost = self._burst  # a single oversized request can still pass when full
            if tokens >= cost:
                self._state[key] = (tokens - cost, now)
                return True, 0.0
            self._state[key] = (tokens, now)
            return False, (cost - tokens) / self._rate

    def forget(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)
