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
from sqlalchemy import func, select

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import BucketStore, Limit, limit
from app.db.models import AuditLog
from tests.factories import DEFAULT_PASSWORD, create_verified_user, login_as, unique_email

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
REGISTER = f"{API}/auth/register"
ME = f"{API}/auth/me"
CHANGE_PASSWORD = f"{API}/auth/me/password"
ORGANISATIONS = f"{API}/organisations/"
ALLOWED_ORIGIN = "http://localhost:5173"
# Read from the table, so these tests follow a change of budget.
LOGIN_LIMIT = rate_limit.ROUTE_LIMITS[("POST", LOGIN)]
REGISTER_LIMIT = rate_limit.ROUTE_LIMITS[("POST", REGISTER)]
DELETE_ME_LIMIT = rate_limit.ROUTE_LIMITS[("DELETE", ME)]
N_LOGIN = LOGIN_LIMIT.times


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


async def test_login_over_the_route_budget_is_limited(client, limits):
    assert await _login_attempts(client, N_LOGIN) == [422] * N_LOGIN

    _assert_limited(await client.post(LOGIN, json={}), 900)


async def test_login_limit_is_per_ip_via_cloudflare_header(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    first = {"CF-Connecting-IP": "203.0.113.1"}
    second = {"CF-Connecting-IP": "203.0.113.2"}

    assert await _login_attempts(client, N_LOGIN, headers=first) == [422] * N_LOGIN
    _assert_limited(await client.post(LOGIN, json={}, headers=first), 900)

    assert (await client.post(LOGIN, json={}, headers=second)).status_code == 422


async def test_cloudflare_header_ignored_without_trusted_proxy(client, limits):
    """Without ``TRUST_PROXY_HEADERS`` a spoofed header cannot buy a fresh bucket."""
    for i in range(N_LOGIN):
        response = await client.post(LOGIN, json={}, headers={"CF-Connecting-IP": f"10.0.0.{i}"})
        assert response.status_code == 422

    _assert_limited(
        await client.post(LOGIN, json={}, headers={"CF-Connecting-IP": "10.0.1.99"}), 900
    )


async def test_login_limit_is_per_ip_via_socket_peer(client, limits):
    from app.main import app

    assert await _login_attempts(client, N_LOGIN) == [422] * N_LOGIN
    _assert_limited(await client.post(LOGIN, json={}), 900)

    transport = httpx.ASGITransport(app=app, client=("198.51.100.7", 4321))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other_ip:
        assert (await other_ip.post(LOGIN, json={})).status_code == 422


async def test_register_over_the_route_budget_is_limited(client, limits):
    n = REGISTER_LIMIT.times
    statuses = [(await client.post(REGISTER, json={})).status_code for _ in range(n)]
    assert statuses == [422] * n

    _assert_limited(await client.post(REGISTER, json={}), 3600)


async def test_sixth_account_deletion_in_an_hour_is_limited(client, limits):
    """``DELETE /auth/me`` checks the current password, so it gets its own tight limit."""
    assert (DELETE_ME_LIMIT.name, DELETE_ME_LIMIT.times, DELETE_ME_LIMIT.seconds) == (
        "auth.me_delete",
        5,
        3600,
    )
    statuses = [(await client.request("DELETE", ME, json={})).status_code for _ in range(5)]
    assert 429 not in statuses
    assert set(statuses) <= {401, 422}

    _assert_limited(await client.request("DELETE", ME, json={}), 3600)


async def test_route_limits_are_independent(client, limits):
    """Exhausting login does not touch register (different route name, same IP)."""
    await _login_attempts(client, N_LOGIN)
    _assert_limited(await client.post(LOGIN, json={}), 900)

    assert (await client.post(REGISTER, json={})).status_code == 422


def test_route_limits_match_the_plan():
    expected = {
        # Generous: a venue Wi-Fi or NAT shares one address; Turnstile and the per-account
        # limits carry the protection (owner decision, 7k).
        ("POST", f"{API}/auth/register"): ("auth.register", 30, 3600),
        ("POST", f"{API}/auth/login"): ("auth.login", 60, 900),
        ("POST", f"{API}/auth/resend-verification"): ("auth.resend_verification", 10, 3600),
        ("POST", f"{API}/auth/password/forgot"): ("auth.password_forgot", 10, 3600),
        ("POST", f"{API}/auth/password/reset"): ("auth.password_reset", 10, 3600),
        ("POST", f"{API}/auth/email/confirm"): ("auth.email_confirm", 10, 3600),
        ("POST", f"{API}/auth/me/password"): ("auth.me_password", 10, 3600),
        ("POST", f"{API}/auth/me/email"): ("auth.me_email", 5, 3600),
        ("DELETE", f"{API}/auth/me"): ("auth.me_delete", 5, 3600),
        ("POST", f"{API}/notifications/unsubscribe"): ("notifications.unsubscribe", 30, 60),
    }
    actual = {
        key: (value.name, value.times, value.seconds)
        for key, value in rate_limit.ROUTE_LIMITS.items()
    }
    assert actual == expected


async def test_trailing_slash_does_not_escape_the_limit(client, limits):
    await _login_attempts(client, N_LOGIN)

    response = await client.post(f"{LOGIN}/", json={})

    _assert_limited(response, 900)


async def test_disabled_flag_means_no_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    rate_limit.reset()

    n_login, n_register = N_LOGIN + 5, REGISTER_LIMIT.times + 3
    assert await _login_attempts(client, n_login) == [422] * n_login
    statuses = [(await client.post(REGISTER, json={})).status_code for _ in range(n_register)]
    assert statuses == [422] * n_register


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
    await _login_attempts(client, N_LOGIN)

    response = await client.post(LOGIN, json={}, headers={"Origin": ALLOWED_ORIGIN})

    _assert_limited(response, 900)
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


async def test_limited_request_is_logged_with_hashed_ip(client, limits):
    await _login_attempts(client, N_LOGIN)
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


def test_float_rounding_never_refuses_an_allowed_hit():
    """``(now + 60) - 60`` can round to just above ``now`` (CI flake 2026-11-02 on a 1/60 s limit):
    the first hit of a fresh key, and a hit exactly one interval later, must still pass."""
    clock = FakeClock()
    clock.now = 1000.0000000000003  # (now + 60.0) - 60.0 > now for this value
    assert (clock.now + 60.0) - 60.0 > clock.now
    store = BucketStore(clock=clock)

    assert store.hit("k", 1, 60) == 0
    assert store.hit("k", 1, 60) > 0
    clock.now += 60
    assert store.hit("k", 1, 60) == 0


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
    rate_limit.account_store().hit("k", 1, 60)
    assert len(rate_limit.store()) == 1
    assert len(rate_limit.account_store()) == 1

    rate_limit.reset()

    assert len(rate_limit.store()) == 0
    assert len(rate_limit.account_store()) == 0


def test_account_store_is_separate_from_the_ip_store():
    assert rate_limit.account_store() is not rate_limit.store()


def test_forget_empties_a_bucket():
    store = BucketStore(clock=FakeClock())
    for _ in range(3):
        store.hit("k", 3, 60)
    assert store.hit("k", 3, 60) > 0

    store.forget("k")

    assert "k" not in store
    assert store.hit("k", 3, 60) == 0


def test_forget_of_an_unknown_key_is_a_no_op():
    store = BucketStore(clock=FakeClock())

    store.forget("k")

    assert "k" not in store


def test_a_full_store_drops_drained_buckets_before_evicting_an_active_one():
    """Flooding new keys must not evict a bucket that is still limiting (a locked account)
    while buckets that are full again could go instead."""
    clock = FakeClock()
    store = BucketStore(max_keys=3, clock=clock)
    store.hit("locked", 1, 3600)  # active for an hour, and the least recently used key
    store.hit("a", 1, 10)
    store.hit("b", 1, 10)
    clock.now += 11  # "a" and "b" drained; still before the periodic sweep

    store.hit("c", 1, 10)

    assert "locked" in store
    assert "a" not in store and "b" not in store
    assert store.hit("locked", 1, 3600) > 0


def test_a_full_store_of_active_buckets_still_evicts_the_oldest():
    clock = FakeClock()
    store = BucketStore(max_keys=2, clock=clock)
    store.hit("old", 1, 3600)
    store.hit("new", 1, 3600)

    store.hit("newest", 1, 3600)

    assert len(store) == 2
    assert "old" not in store


# --- IP normalisation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:0DB8:0001:0002:0000:0000:0000:0001", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("::1", "::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        ("not-an-ip", "not-an-ip"),
        ("", rate_limit.UNKNOWN_IP),
        (None, rate_limit.UNKNOWN_IP),
    ],
)
def test_bucket_ip_normalisation(raw, expected):
    assert rate_limit.bucket_ip(raw) == expected


async def test_ipv6_addresses_in_one_64_share_a_bucket(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    for i in range(1, N_LOGIN + 1):
        response = await client.post(
            LOGIN, json={}, headers={"CF-Connecting-IP": f"2001:db8:1:2::{i:x}"}
        )
        assert response.status_code == 422

    same_64 = {"CF-Connecting-IP": "2001:db8:1:2:ffff:ffff:ffff:ffff"}
    _assert_limited(await client.post(LOGIN, json={}, headers=same_64), 900)

    other_64 = {"CF-Connecting-IP": "2001:db8:1:3::1"}
    assert (await client.post(LOGIN, json={}, headers=other_64)).status_code == 422


async def test_ipv4_mapped_ipv6_shares_the_ipv4_bucket(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    ipv4 = {"CF-Connecting-IP": "203.0.113.9"}
    assert await _login_attempts(client, N_LOGIN, headers=ipv4) == [422] * N_LOGIN

    _assert_limited(
        await client.post(LOGIN, json={}, headers={"CF-Connecting-IP": "::ffff:203.0.113.9"}),
        900,
    )


# --- per-account limits on failed password checks ---------------------------------------------


def _ip(i: int) -> dict[str, str]:
    """A distinct client IP per attempt, so only the per-account limit can refuse."""
    return {"CF-Connecting-IP": f"198.51.100.{i}"}


@pytest.fixture
def proxied(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)


async def _committed_user(db_session, cleanup_users, **kwargs):
    user = await create_verified_user(db_session, **kwargs)
    cleanup_users.add(user.email)
    await db_session.commit()
    return user


async def _fail_logins(client, email: str, n: int, first_ip: int = 1) -> list[int]:
    statuses = []
    for i in range(first_ip, first_ip + n):
        response = await client.post(
            LOGIN, json={"email": email, "password": "wrong-password-guess"}, headers=_ip(i)
        )
        statuses.append(response.status_code)
    return statuses


async def _login_failed_rows(db_session, user_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "auth.login_failed",
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
        )
    )
    return await db_session.scalar(stmt)


def test_account_limits():
    assert rate_limit.LOGIN_ACCOUNT_LIMIT == Limit("auth.login_account", 10, 900)
    assert rate_limit.PASSWORD_CHECK_ACCOUNT_LIMIT == Limit("auth.password_check_account", 10, 3600)


async def test_login_account_limit_blocks_even_the_right_password(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    assert await _fail_logins(client, user.email, 10) == [401] * 10

    response = await client.post(
        LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(50)
    )

    _assert_limited(response, 900)
    assert "set-cookie" not in response.headers
    # The refused attempt never reached the password check: no audit row for it.
    assert await _login_failed_rows(db_session, user.id) == 10


async def test_login_account_limit_does_not_touch_other_accounts(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    other = await _committed_user(db_session, cleanup_users)
    await _fail_logins(client, user.email, 10)

    # Same IP as one of the failures above (its own per-IP bucket has room left).
    response = await client.post(
        LOGIN, json={"email": other.email, "password": DEFAULT_PASSWORD}, headers=_ip(1)
    )

    assert response.status_code == 200, response.text


async def test_login_account_limit_ignores_case_and_whitespace(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    local, domain = user.email.split("@")
    variants = [
        user.email,
        user.email.upper(),
        f"  {user.email}  ",
        f"{local.upper()}@{domain}",
        f"{local}@{domain.upper()}",
    ]
    for i in range(10):
        response = await client.post(
            LOGIN,
            json={"email": variants[i % len(variants)], "password": "wrong-password-guess"},
            headers=_ip(i + 1),
        )
        assert response.status_code == 401, response.text

    response = await client.post(
        LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(50)
    )
    _assert_limited(response, 900)


async def test_login_account_limit_unknown_email_behaves_the_same(client, limits, proxied):
    email = unique_email("nobody")
    assert await _fail_logins(client, email, 10) == [401] * 10

    response = await client.post(
        LOGIN, json={"email": email, "password": "wrong-password-guess"}, headers=_ip(50)
    )

    _assert_limited(response, 900)


async def test_login_success_does_not_count(client, limits, proxied, db_session, cleanup_users):
    user = await _committed_user(db_session, cleanup_users)
    for i in range(12):
        response = await client.post(
            LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(i + 1)
        )
        assert response.status_code == 200, response.text


async def test_login_account_limit_logs_no_email(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    await _fail_logins(client, user.email, 10)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))

    with structlog.testing.capture_logs() as logs:
        await client.post(
            LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(50)
        )

    events = [e for e in logs if e["event"] == "rate.limited"]
    assert len(events) == 1
    assert events[0]["limit"] == "auth.login_account"
    assert user.email.split("@")[0] not in repr(logs)


async def test_login_account_key_is_keyed_and_hides_the_email():
    key = rate_limit.login_account_key("Maria@Example.org")

    assert key == rate_limit.login_account_key("  maria@example.org ")
    assert "maria" not in key.lower()
    assert hashlib.sha256(b"maria@example.org").hexdigest() not in key


async def test_change_password_account_limit(client, limits, proxied, db_session, cleanup_users):
    user = await _committed_user(db_session, cleanup_users)
    await login_as(client, user)
    body = {"current_password": "wrong-password-guess", "new_password": "estuary-levee-77-x"}
    for i in range(10):
        response = await client.post(CHANGE_PASSWORD, json=body, headers=_ip(i + 1))
        assert response.status_code == 400, response.text

    right = {"current_password": DEFAULT_PASSWORD, "new_password": "estuary-levee-77-x"}
    _assert_limited(await client.post(CHANGE_PASSWORD, json=right, headers=_ip(50)), 3600)
    # The bucket is per account, shared by every current-password check.
    _assert_limited(
        await client.request(
            "DELETE", ME, json={"current_password": DEFAULT_PASSWORD}, headers=_ip(51)
        ),
        3600,
    )
    assert (await client.get(ME)).status_code == 200


async def test_delete_account_limit(
    client, limits, proxied, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed_user(db_session, cleanup_users)
    cleanup_user_ids.add(user.id)
    await login_as(client, user)
    for i in range(10):
        response = await client.request(
            "DELETE", ME, json={"current_password": "wrong-password-guess"}, headers=_ip(i + 1)
        )
        assert response.status_code == 400, response.text

    response = await client.request(
        "DELETE", ME, json={"current_password": DEFAULT_PASSWORD}, headers=_ip(50)
    )

    _assert_limited(response, 3600)
    assert (await client.get(ME)).status_code == 200


async def test_password_check_success_does_not_count(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    await login_as(client, user)
    for i in range(12):
        response = await client.post(
            f"{API}/auth/me/email",
            json={"new_email": user.email.upper(), "current_password": DEFAULT_PASSWORD},
            headers=_ip(i + 1),
        )
        assert response.status_code == 422, response.text


async def test_login_success_clears_the_account_bucket(
    client, limits, proxied, db_session, cleanup_users
):
    """The owner's typo after an attacker's 9 failures must not lock them out: a correct
    password empties the bucket (only someone holding the password can do that)."""
    user = await _committed_user(db_session, cleanup_users)
    assert await _fail_logins(client, user.email, 9) == [401] * 9
    response = await client.post(
        LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(100)
    )
    assert response.status_code == 200, response.text

    assert await _fail_logins(client, user.email, 10, first_ip=20) == [401] * 10
    response = await client.post(
        LOGIN, json={"email": user.email, "password": "wrong-password-guess"}, headers=_ip(101)
    )
    _assert_limited(response, 900)


async def test_password_check_success_clears_the_account_bucket(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    await login_as(client, user)

    async def check(password: str, i: int) -> int:
        response = await client.post(
            f"{API}/auth/me/email",
            json={"new_email": user.email.upper(), "current_password": password},
            headers=_ip(i),
        )
        return response.status_code

    assert [await check("wrong-password-guess", i) for i in range(1, 10)] == [400] * 9
    assert await check(DEFAULT_PASSWORD, 100) == 422  # right password; same address
    assert [await check("wrong-password-guess", i) for i in range(20, 30)] == [400] * 10
    assert await check("wrong-password-guess", 101) == 429


async def test_known_accounts_are_keyed_by_user_id(
    client, limits, proxied, db_session, cleanup_users
):
    user = await _committed_user(db_session, cleanup_users)
    await login_as(client, user)  # a success empties the login bucket, so sign in first
    await _fail_logins(client, user.email.upper(), 1)
    await client.post(
        CHANGE_PASSWORD,
        json={"current_password": "wrong-password-guess", "new_password": "estuary-levee-77-x"},
        headers=_ip(2),
    )

    store = rate_limit.account_store()
    assert f"auth.login_account|user:{user.id}" in store
    assert f"auth.password_check_account|user:{user.id}" in store
    assert len(store) == 2


async def test_unknown_addresses_are_keyed_by_a_keyed_hash(client, limits, proxied):
    email = unique_email("nobody")
    await _fail_logins(client, email, 1)

    key = f"auth.login_account|{rate_limit.login_account_key(email)}"
    assert key in rate_limit.account_store()
    assert email.split("@")[0] not in key


async def test_account_limits_off_when_rate_limiting_is_disabled(
    client, monkeypatch, proxied, db_session, cleanup_users
):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    rate_limit.reset()
    user = await _committed_user(db_session, cleanup_users)
    assert await _fail_logins(client, user.email, 12) == [401] * 12

    response = await client.post(
        LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD}, headers=_ip(50)
    )
    assert response.status_code == 200, response.text

    body = {"current_password": "wrong-password-guess", "new_password": "estuary-levee-77-x"}
    for i in range(12):
        response = await client.post(CHANGE_PASSWORD, json=body, headers=_ip(i + 1))
        assert response.status_code == 400, response.text
    assert len(rate_limit.account_store()) == 0
