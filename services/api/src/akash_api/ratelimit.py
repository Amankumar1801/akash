"""Per-principal token buckets (in-process; swap for Redis when running several instances)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[tuple[str, str], tuple[float, float]] = {}  # -> (tokens, last)

    def check(self, principal: str, bucket: str, limit_per_min: int) -> float | None:
        """None if allowed (a token is consumed), else seconds until a token is available."""
        rate, now = limit_per_min / 60.0, self._clock()
        with self._lock:
            tokens, last = self._state.get((principal, bucket), (float(limit_per_min), now))
            tokens = min(float(limit_per_min), tokens + (now - last) * rate)
            if tokens < 1.0:
                self._state[(principal, bucket)] = (tokens, now)
                return (1.0 - tokens) / rate
            self._state[(principal, bucket)] = (tokens - 1.0, now)
            return None
