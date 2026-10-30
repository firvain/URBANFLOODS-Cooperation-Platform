"""Increment 1g: rate limiting (``app/core/rate_limit.py``).

Limits are off in the test env (``RATE_LIMIT_ENABLED=false`` in conftest); the ``limits``
fixture switches them on and empties the store before and after each test.

The auth limits are applied by the middleware from ``ROUTE_LIMITS`` (keyed by method and path), so
they count every attempt, including ones the endpoint would reject with 422. The tests use
invalid bodies so that no rows are written.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator

import httpx
import pytest
import structlog
from fastapi import Depends

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import BucketStore, Limit, limit

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
REGISTER = f"{API}/auth/register"
ORGANISATIONS = f"{API}/organisations/"
ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


def _assert_limited(response: httpx.Response, max_retry_after: int) -> None:
    assert response.status_code == 429, response.text
    assert response.json() == {
        "detail": {"code": "rate.limited", "message": "Too many requests. Please try again later."}
    }
    retry_after = int(response.headers["retry-after"])
    assert 1 <= retry_after <= max_retry_after


async def _login_attempts(client: httpx.AsyncClient, n: int, **kwargs) -> list[int]:
    return [(await client.post(LOGIN, json={}, **kwargs)).status_code for _ in range(n)]


# --- auth route limits ------------------------------------------------------------------------


async def test_eleventh_login_in_fifteen_minutes_is_limited(client, limits):
    assert await _login_attempts(client, 10) == [422] * 10

    _assert_limited(await client.post(LOGIN, json={}), 900)


async def test_login_limit_is_per_ip_via_cloudflare_header(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    first = {"CF-Connecting-IP": "203.0.113.1"}
    second = {"CF-Connecting-IP": "203.0.113.2"}

    assert await _login_attempts(client, 10, headers=first) == [422] * 10
    _assert_limited(await client.post(LOGIN, json={}, headers=first), 900)

    assert (await client.post(LOGIN, json={}, headers=second)).status_code == 422


async def test_cloudflare_header_ignored_without_trusted_proxy(client, limits):
    """Without ``TRUST_PROXY_HEADERS`` a spoofed header cannot buy a fresh bucket."""
    for i in range(10):
        response = await client.post(LOGIN, json={}, headers={"CF-Connecting-IP": f"10.0.0.{i}"})
        assert response.status_code == 422

    _assert_limited(
        await client.post(LOGIN, json={}, headers={"CF-Connecting-IP": "10.0.0.99"}), 900
    )


async def test_login_limit_is_per_ip_via_socket_peer(client, limits):
    from app.main import app

    assert await _login_attempts(client, 10) == [422] * 10
    _assert_limited(await client.post(LOGIN, json={}), 900)

    transport = httpx.ASGITransport(app=app, client=("198.51.100.7", 4321))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other_ip:
        assert (await other_ip.post(LOGIN, json={})).status_code == 422


async def test_sixth_register_in_an_hour_is_limited(client, limits):
    statuses = [(await client.post(REGISTER, json={})).status_code for _ in range(5)]
    assert statuses == [422] * 5

    _assert_limited(await client.post(REGISTER, json={}), 3600)


async def test_route_limits_are_independent(client, limits):
    """Exhausting login does not touch register (different route name, same IP)."""
    await _login_attempts(client, 10)
    _assert_limited(await client.post(LOGIN, json={}), 900)

    assert (await client.post(REGISTER, json={})).status_code == 422


def test_route_limits_match_the_plan():
    expected = {
        ("POST", f"{API}/auth/register"): ("auth.register", 5, 3600),
        ("POST", f"{API}/auth/login"): ("auth.login", 10, 900),
        ("POST", f"{API}/auth/resend-verification"): ("auth.resend_verification", 3, 3600),
        ("POST", f"{API}/auth/password/forgot"): ("auth.password_forgot", 3, 3600),
        ("POST", f"{API}/auth/password/reset"): ("auth.password_reset", 10, 3600),
        ("POST", f"{API}/auth/email/confirm"): ("auth.email_confirm", 10, 3600),
        ("POST", f"{API}/auth/me/password"): ("auth.me_password", 10, 3600),
        ("POST", f"{API}/auth/me/email"): ("auth.me_email", 5, 3600),
    }
    actual = {
        key: (value.name, value.times, value.seconds)
        for key, value in rate_limit.ROUTE_LIMITS.items()
    }
    assert actual == expected


async def test_trailing_slash_does_not_escape_the_limit(client, limits):
    await _login_attempts(client, 10)

    response = await client.post(f"{LOGIN}/", json={})

    _assert_limited(response, 900)


async def test_disabled_flag_means_no_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    rate_limit.reset()

    assert await _login_attempts(client, 15) == [422] * 15
    statuses = [(await client.post(REGISTER, json={})).status_code for _ in range(8)]
    assert statuses == [422] * 8


# --- generic guard ----------------------------------------------------------------------------


async def test_generic_api_guard(client, limits, monkeypatch, database_url):
    monkeypatch.setattr(rate_limit, "DEFAULT_LIMIT", Limit("api.default", 3, 60))

    statuses = [(await client.get(ORGANISATIONS)).status_code for _ in range(3)]
    assert statuses == [200] * 3

    _assert_limited(await client.get(ORGANISATIONS), 60)
    # Probes are outside /api/ and never limited.
    assert (await client.get("/health")).status_code == 200


async def test_generic_guard_default_is_300_per_minute():
    assert (rate_limit.DEFAULT_LIMIT.times, rate_limit.DEFAULT_LIMIT.seconds) == (300, 60)


async def test_cors_preflight_is_not_counted(client, limits, monkeypatch):
    monkeypatch.setattr(rate_limit, "DEFAULT_LIMIT", Limit("api.default", 1, 60))
    preflight = {"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"}

    for _ in range(3):
        assert (await client.options(LOGIN, headers=preflight)).status_code == 200
    assert (await client.post(LOGIN, json={})).status_code == 422


async def test_429_carries_cors_headers(client, limits):
    """The SPA shows a toast on 429, so the browser must let it read the response."""
    await _login_attempts(client, 10)

    response = await client.post(LOGIN, json={}, headers={"Origin": ALLOWED_ORIGIN})

    _assert_limited(response, 900)
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


async def test_limited_request_is_logged_with_hashed_ip(client, limits):
    await _login_attempts(client, 10)
    # The app lifespan filters below WARNING in tests; conftest restores the config afterwards.
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))

    with structlog.testing.capture_logs() as logs:
        await client.post(LOGIN, json={})

    events = [e for e in logs if e["event"] == "rate.limited"]
    assert len(events) == 1
    assert events[0]["log_level"] == "info"
    assert events[0]["limit"] == "auth.login"
    ip_hash = events[0]["ip_hash"]
    assert len(ip_hash) == 12
    assert ip_hash != hashlib.sha256(b"127.0.0.1").hexdigest()[:12]
    assert "127.0.0.1" not in repr(logs)


# --- dependency factory -----------------------------------------------------------------------


async def test_limit_dependency(limits):
    from app.main import create_app

    app = create_app()

    @app.post("/_limited", dependencies=[Depends(limit("test.dep", 2, 60))])
    async def limited() -> dict:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.post("/_limited")).status_code == 200
        assert (await ac.post("/_limited")).status_code == 200
        _assert_limited(await ac.post("/_limited"), 60)


async def test_limit_dependency_respects_disabled_flag(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    rate_limit.reset()
    app = create_app()

    @app.post("/_limited", dependencies=[Depends(limit("test.dep", 1, 60))])
    async def limited() -> dict:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(3):
            assert (await ac.post("/_limited")).status_code == 200


def test_limit_rejects_nonsense():
    with pytest.raises(ValueError):
        limit("x", 0, 60)
    with pytest.raises(ValueError):
        limit("x", 1, 0)


# --- bucket store -----------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_bucket_allows_burst_then_refills():
    clock = FakeClock()
    store = BucketStore(clock=clock)

    for _ in range(10):
        assert store.hit("k", 10, 900) == 0
    retry = store.hit("k", 10, 900)
    assert retry == pytest.approx(90)  # one token per 900/10 seconds

    clock.now += 89
    assert store.hit("k", 10, 900) == pytest.approx(1)
    clock.now += 1
    assert store.hit("k", 10, 900) == 0
    assert store.hit("k", 10, 900) > 0


def test_rejected_hits_do_not_extend_the_wait():
    clock = FakeClock()
    store = BucketStore(clock=clock)
    store.hit("k", 1, 60)

    for _ in range(50):
        store.hit("k", 1, 60)

    clock.now += 60
    assert store.hit("k", 1, 60) == 0


def test_full_bucket_after_window_is_expired_and_swept():
    clock = FakeClock()
    store = BucketStore(clock=clock)
    store.hit("a", 5, 60)
    store.hit("b", 5, 600)

    clock.now += 61
    store.sweep()

    assert "a" not in store
    assert "b" in store


def test_memory_cap_evicts_the_oldest_key():
    clock = FakeClock()
    store = BucketStore(max_keys=3, clock=clock)
    for key in ("a", "b", "c"):
        store.hit(key, 5, 3600)
        clock.now += 1
    store.hit("a", 5, 3600)  # touching "a" makes "b" the least recently used

    store.hit("d", 5, 3600)

    assert len(store) == 3
    assert "b" not in store
    assert {"a", "c", "d"} <= {k for k in ("a", "b", "c", "d") if k in store}


def test_memory_cap_holds_under_many_keys():
    store = BucketStore(max_keys=100, clock=FakeClock())
    for i in range(1000):
        store.hit(f"ip-{i}", 5, 3600)

    assert len(store) == 100
    assert "ip-0" not in store
    assert "ip-999" in store


def test_default_store_is_capped():
    assert rate_limit.MAX_KEYS == 50_000


def test_reset_clears_the_store(limits):
    rate_limit.store().hit("k", 1, 60)
    assert len(rate_limit.store()) == 1

    rate_limit.reset()

    assert len(rate_limit.store()) == 0
