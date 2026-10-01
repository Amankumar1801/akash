import httpx
import pytest
from akash_core.errors import CircuitOpen, ProviderError
from akash_data.http import CircuitBreaker, ResilientClient, TokenBucket
from conftest import client_for


def test_retries_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": 1})

    assert client_for(h).get("http://x").json() == {"ok": 1}
    assert calls["n"] == 3


def test_gives_up_after_max_retries():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(500)

    with pytest.raises(ProviderError):
        client_for(h, max_retries=2).get("http://x")
    assert calls["n"] == 3


def test_4xx_not_retried_and_does_not_trip_breaker():
    calls = {"n": 0}
    br = CircuitBreaker(failure_threshold=1)

    def h(req):
        calls["n"] += 1
        return httpx.Response(404)

    c = client_for(h, breaker=br)
    with pytest.raises(ProviderError):
        c.get("http://x")
    assert calls["n"] == 1 and br.state == "closed"


def test_transport_errors_retried():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200)

    assert client_for(h).get("http://x").status_code == 200


def test_retry_after_honoured():
    sleeps = []
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "7"}) if calls["n"] == 1 else httpx.Response(200)

    c = ResilientClient("t", httpx.Client(transport=httpx.MockTransport(h)), sleep=sleeps.append)
    c.get("http://x")
    assert sleeps == [7.0]


def test_circuit_opens_then_recovers():
    now = {"t": 0.0}
    br = CircuitBreaker(failure_threshold=2, cooldown_s=30, clock=lambda: now["t"])
    ok = {"v": False}

    def h(req):
        return httpx.Response(200) if ok["v"] else httpx.Response(503)

    c = client_for(h, breaker=br, max_retries=0)
    for _ in range(2):
        with pytest.raises(ProviderError):
            c.get("http://x")
    assert br.state == "open"
    with pytest.raises(CircuitOpen):
        c.get("http://x")
    now["t"] = 31.0
    assert br.state == "half_open"
    ok["v"] = True
    assert c.get("http://x").status_code == 200
    assert br.state == "closed"


def test_token_bucket_throttles():
    now = {"t": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        now["t"] += s

    b = TokenBucket(rate_per_s=2.0, capacity=2.0, clock=lambda: now["t"], sleep=sleep)
    for _ in range(5):
        b.acquire()
    assert sum(slept) == pytest.approx(1.5)  # 2 burst, then 3 more at 0.5s each
