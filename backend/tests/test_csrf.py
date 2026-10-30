"""Increment 1g: CSRF defence middleware (``app/core/csrf.py``).

Unsafe requests (POST/PUT/PATCH/DELETE) that carry the session cookie must send
``X-Requested-With: XMLHttpRequest`` and, if they name an origin (``Origin``, else ``Referer``),
one that is allowed. Requests without the cookie only get the origin check, so curl-style use of
the public endpoints keeps working while a cross-site page cannot post to login (login CSRF).

The ``client`` fixture sends the header by default (like the SPA); ``bare`` is a client on the
same app without it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import structlog

from app.core.config import settings
from tests.factories import DEFAULT_PASSWORD, create_verified_user, login_as

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
LOGOUT = f"{API}/auth/logout"
ME = f"{API}/auth/me"
COOKIE = settings.SESSION_COOKIE_NAME
XRW = {"X-Requested-With": "XMLHttpRequest"}
ALLOWED_ORIGIN = "http://localhost:5173"
EVIL_ORIGIN = "https://evil.example"


@pytest.fixture
async def bare(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the running app that does NOT send ``X-Requested-With`` by default."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def signed_in(client, bare, db_session, cleanup_users):
    """A verified user signed in through ``client``; ``bare`` shares the session cookie."""
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    await db_session.commit()
    await login_as(client, user)
    bare.cookies.set(COOKIE, client.cookies[COOKIE])
    return user


def _assert_csrf(response: httpx.Response, code: str) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["message"]


# --- cookie-authenticated unsafe requests ------------------------------------------------------


async def test_client_without_header_is_rejected(bare, signed_in):
    _assert_csrf(await bare.post(LOGOUT), "security.csrf")
    # The rejected request never reached the endpoint: the session is still valid.
    assert (await bare.get(ME)).status_code == 200


async def test_cookie_post_with_header_passes(bare, signed_in):
    response = await bare.post(LOGOUT, headers=XRW)

    assert response.status_code == 204
    assert (await bare.get(ME)).status_code == 401


async def test_header_value_is_case_insensitive(bare, signed_in):
    response = await bare.post(LOGOUT, headers={"X-Requested-With": "xmlhttprequest"})

    assert response.status_code == 204


async def test_wrong_header_value_is_rejected(bare, signed_in):
    _assert_csrf(await bare.post(LOGOUT, headers={"X-Requested-With": "fetch"}), "security.csrf")


@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
async def test_other_unsafe_methods_are_checked(bare, signed_in, method):
    _assert_csrf(await bare.request(method, ME), "security.csrf")


async def test_cookie_post_from_evil_origin_is_rejected(client, signed_in):
    response = await client.post(LOGOUT, headers={"Origin": EVIL_ORIGIN})

    _assert_csrf(response, "security.csrf_origin")
    assert (await client.get(ME)).status_code == 200


async def test_cookie_post_from_allowed_origin_passes(client, signed_in):
    response = await client.post(LOGOUT, headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 204


async def test_cookie_post_from_own_origin_passes(client, signed_in):
    # base_url is http://test, so the request's own origin is http://test.
    response = await client.post(LOGOUT, headers={"Origin": "http://test"})

    assert response.status_code == 204


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://localhost:5174",  # same host, other port
        "https://localhost:5173",  # other scheme
        "http://localhost:5173.evil.example",
        "http://test.evil.example",
        "not a url",
    ],
)
async def test_lookalike_origins_are_rejected(client, signed_in, origin):
    _assert_csrf(await client.post(LOGOUT, headers={"Origin": origin}), "security.csrf_origin")


async def test_evil_referer_without_origin_is_rejected(client, signed_in):
    response = await client.post(LOGOUT, headers={"Referer": f"{EVIL_ORIGIN}/x"})

    _assert_csrf(response, "security.csrf_origin")


async def test_allowed_referer_without_origin_passes(client, signed_in):
    response = await client.post(LOGOUT, headers={"Referer": f"{ALLOWED_ORIGIN}/account?x=1"})

    assert response.status_code == 204


async def test_origin_takes_precedence_over_referer(client, signed_in):
    response = await client.post(
        LOGOUT, headers={"Origin": ALLOWED_ORIGIN, "Referer": f"{EVIL_ORIGIN}/x"}
    )

    assert response.status_code == 204


async def test_forwarded_proto_is_honoured_only_behind_trusted_proxy(
    client, signed_in, monkeypatch
):
    headers = {"Origin": "https://test", "X-Forwarded-Proto": "https"}

    _assert_csrf(await client.post(LOGOUT, headers=headers), "security.csrf_origin")

    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    assert (await client.post(LOGOUT, headers=headers)).status_code == 204


async def test_safe_method_with_cookie_needs_no_header(bare, signed_in):
    response = await bare.get(ME, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 200


# --- requests without the session cookie -------------------------------------------------------


async def test_login_without_cookie_origin_or_header_passes(bare, db_session, cleanup_users):
    """curl-style public use: no cookie, no Origin, no custom header."""
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    await db_session.commit()

    response = await bare.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})

    assert response.status_code == 200
    assert COOKIE in bare.cookies


async def test_login_from_evil_origin_is_rejected(bare):
    """Login CSRF: a cross-site page posting the attacker's credentials."""
    response = await bare.post(
        LOGIN, json={"email": "a@example.org", "password": "x"}, headers={"Origin": EVIL_ORIGIN}
    )

    _assert_csrf(response, "security.csrf_origin")
    assert COOKIE not in bare.cookies


async def test_cookieless_evil_origin_is_rejected_even_with_header(bare):
    response = await bare.post(LOGIN, json={}, headers={"Origin": EVIL_ORIGIN, **XRW})

    _assert_csrf(response, "security.csrf_origin")


async def test_cookieless_evil_referer_is_rejected(bare):
    response = await bare.post(LOGIN, json={}, headers={"Referer": f"{EVIL_ORIGIN}/login"})

    _assert_csrf(response, "security.csrf_origin")


async def test_cookieless_allowed_origin_without_header_passes(bare):
    response = await bare.post(LOGIN, json={}, headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 422


# --- exemptions, CORS, logging ----------------------------------------------------------------


async def test_health_is_untouched(bare):
    bare.cookies.set(COOKIE, "x" * 43)

    assert (await bare.get("/health")).status_code == 200
    # Unsafe method on an exempt path reaches the router (405), not the CSRF check (403).
    assert (await bare.post("/health", headers={"Origin": EVIL_ORIGIN})).status_code == 405
    assert (await bare.post("/health/ready")).status_code == 405


async def test_openapi_is_untouched(bare):
    bare.cookies.set(COOKIE, "x" * 43)

    assert (await bare.get(f"{API}/openapi.json")).status_code == 200
    assert (await bare.post(f"{API}/openapi.json")).status_code == 405


async def test_cors_preflight_allows_the_custom_header(client):
    response = await client.options(
        LOGOUT,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-requested-with",
        },
    )

    assert response.status_code == 200
    assert "x-requested-with" in response.headers["access-control-allow-headers"].lower()


async def test_rejection_carries_cors_headers(bare, signed_in):
    """The SPA must be able to read the 403 body (the middleware sits inside CORS)."""
    response = await bare.post(LOGOUT, headers={"Origin": ALLOWED_ORIGIN})

    _assert_csrf(response, "security.csrf")
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "x-request-id" in response.headers


async def test_rejection_is_logged_without_the_cookie(bare, signed_in):
    raw_cookie = bare.cookies[COOKIE]

    with structlog.testing.capture_logs() as logs:
        await bare.post(LOGOUT, headers={"Origin": EVIL_ORIGIN, **XRW})

    events = [e for e in logs if e["event"] == "security.csrf_rejected"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["method"] == "POST"
    assert events[0]["path"] == LOGOUT
    assert events[0]["reason"] == "security.csrf_origin"
    assert raw_cookie not in repr(logs)
