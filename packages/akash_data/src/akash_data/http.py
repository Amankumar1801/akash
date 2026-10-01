"""Resilient HTTP: retries with full-jitter backoff, token-bucket rate limiting, circuit breaker."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from akash_core.errors import CircuitOpen, ProviderError

RETRY_STATUS = {429, 500, 502, 503, 504}


class TokenBucket:
    def __init__(
        self,
        rate_per_s: float,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate = rate_per_s
        self.capacity = capacity if capacity is not None else max(1.0, rate_per_s)
        self._tokens = self.capacity
        self._clock, self._sleep = clock, sleep
        self._last = clock()

    def acquire(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens < 1.0:
            self._sleep((1.0 - self._tokens) / self.rate)
            self._last = self._clock()
            self._tokens = 0.0
        else:
            self._tokens -= 1.0


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self.clock() - self._opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def before_call(self, name: str) -> None:
        if self.state == "open":
            raise CircuitOpen(f"{name}: circuit open, shedding load")

    def record_success(self) -> None:
        self._failures, self._opened_at = 0, None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold or self.state == "half_open":
            self._opened_at = self.clock()


class ResilientClient:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        bucket: TokenBucket | None = None,
        breaker: CircuitBreaker | None = None,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.name, self._client = name, client
        self.bucket = bucket
        self.breaker = breaker or CircuitBreaker()
        self.max_retries, self.backoff_base_s = max_retries, backoff_base_s
        self._sleep, self._rng = sleep, rng or random.Random()
        self.last_error: str | None = None

    def request(self, method: str, url: str, **kw: object) -> httpx.Response:
        self.breaker.before_call(self.name)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.bucket:
                self.bucket.acquire()
            try:
                resp = self._client.request(method, url, **kw)  # type: ignore[arg-type]
            except httpx.TransportError as e:
                last = e
            else:
                if resp.status_code in RETRY_STATUS:
                    last = ProviderError(f"{self.name}: HTTP {resp.status_code}")
                    if attempt < self.max_retries:
                        self._sleep(self._delay(attempt, resp))
                        continue
                elif resp.status_code >= 400:
                    # client error: our fault, not provider ill-health; don't retry/trip breaker
                    raise ProviderError(f"{self.name}: HTTP {resp.status_code} for {url}")
                else:
                    self.breaker.record_success()
                    self.last_error = None
                    return resp
            if attempt < self.max_retries and not isinstance(last, ProviderError):
                self._sleep(self._delay(attempt, None))
        self.breaker.record_failure()
        self.last_error = str(last)
        raise ProviderError(f"{self.name}: failed after {self.max_retries + 1} attempts: {last}")

    def _delay(self, attempt: int, resp: httpx.Response | None) -> float:
        if resp is not None and (ra := resp.headers.get("Retry-After")):
            try:
                return min(float(ra), 60.0)
            except ValueError:
                pass
        return self._rng.uniform(0, self.backoff_base_s * (2**attempt))

    def get(self, url: str, **kw: object) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: object) -> httpx.Response:
        return self.request("POST", url, **kw)
