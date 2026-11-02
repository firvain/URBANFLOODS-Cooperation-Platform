"""Increment 7l: ``SessionCookieRefreshMiddleware`` (pure ASGI, no database).

The middleware re-sends the session cookie with a fresh ``Max-Age`` when the request's auth
dependency slid the session expiry, unless the response already sets or clears the cookie.
End-to-end behaviour (login, logout, revocation) is covered in ``test_auth_session.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.core.config import settings
from app.core.session_cookie import REFRESH_STATE_KEY, SessionCookieRefreshMiddleware

COOKIE = settings.SESSION_COOKIE_NAME
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
RAW = "raw-token-value"


def _inner_app(
    *,
    refresh_to: datetime | None,
    headers: list[tuple[bytes, bytes]] | None = None,
    status: int = 200,
):
    async def app(scope, receive, send):
        if refresh_to is not None:
            scope["state"][REFRESH_STATE_KEY] = refresh_to
        await send(
            {"type": "http.response.start", "status": status, "headers": list(headers or [])}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return app


async def _run(app, *, cookie: str | None = f"{COOKIE}={RAW}") -> list[dict]:
    headers = [(b"cookie", cookie.encode("latin-1"))] if cookie else []
    scope = {"type": "http", "method": "GET", "path": "/x", "headers": headers}
    sent: list[dict] = []

    async def receive():  # pragma: no cover - never called
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    await SessionCookieRefreshMiddleware(app)(scope, receive, send)
    return sent


def _set_cookies(messages: list[dict]) -> list[str]:
    start = next(m for m in messages if m["type"] == "http.response.start")
    return [v.decode("latin-1") for k, v in start["headers"] if k.lower() == b"set-cookie"]


@freeze_time(NOW)
async def test_refresh_appends_cookie_with_remaining_lifetime():
    expires = NOW + timedelta(days=30)

    (cookie,) = _set_cookies(await _run(_inner_app(refresh_to=expires)))

    assert cookie.startswith(f"{COOKIE}={RAW};")
    lowered = cookie.lower()
    assert f"max-age={30 * 86400}" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered


@freeze_time(NOW)
async def test_refresh_matches_the_login_cookie_format(monkeypatch):
    """Same attributes and serialisation as ``Response.set_cookie(**session_cookie_params)``."""
    from starlette.responses import Response

    from app.core.security import session_cookie_params

    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    expected = Response()
    expected.set_cookie(value=RAW, **session_cookie_params(settings))
    (expected_cookie,) = [
        v.decode("latin-1") for k, v in expected.raw_headers if k == b"set-cookie"
    ]

    (cookie,) = _set_cookies(
        await _run(_inner_app(refresh_to=NOW + timedelta(days=settings.SESSION_TTL_DAYS)))
    )

    assert cookie == expected_cookie
    assert "secure" in cookie.lower()


@freeze_time(NOW)
async def test_insecure_setting_omits_secure_flag(monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)

    (cookie,) = _set_cookies(await _run(_inner_app(refresh_to=NOW + timedelta(days=30))))

    assert "secure" not in cookie.lower()


@freeze_time(NOW)
@pytest.mark.parametrize("status", [400, 403, 404, 422, 429, 500, 503])
async def test_error_status_adds_nothing(status):
    """An error response rolled the touch back: re-sending the cookie would let it drift from the
    stored expiry (and every failing request would re-send it)."""
    app = _inner_app(refresh_to=NOW + timedelta(days=30), status=status)

    assert _set_cookies(await _run(app)) == []


@freeze_time(NOW)
@pytest.mark.parametrize("status", [200, 201, 204, 304])
async def test_success_and_redirect_statuses_refresh(status):
    app = _inner_app(refresh_to=NOW + timedelta(days=30), status=status)

    (cookie,) = _set_cookies(await _run(app))
    assert cookie.startswith(f"{COOKIE}={RAW};")


async def test_no_refresh_requested_adds_nothing():
    assert _set_cookies(await _run(_inner_app(refresh_to=None))) == []


@freeze_time(NOW)
@pytest.mark.parametrize(
    "existing",
    [
        f"{COOKIE}=new-token; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax",
        f'{COOKIE}=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/; SameSite=lax',
    ],
    ids=["new-session", "cleared"],
)
async def test_response_that_sets_the_cookie_is_left_alone(existing):
    app = _inner_app(
        refresh_to=NOW + timedelta(days=30),
        headers=[(b"set-cookie", existing.encode("latin-1"))],
    )

    assert _set_cookies(await _run(app)) == [existing]


@freeze_time(NOW)
async def test_other_cookies_do_not_block_the_refresh():
    other = f"{COOKIE}_other=1; Path=/"
    app = _inner_app(
        refresh_to=NOW + timedelta(days=30), headers=[(b"set-cookie", other.encode("latin-1"))]
    )

    cookies = _set_cookies(await _run(app))

    assert cookies[0] == other
    assert len(cookies) == 2
    assert cookies[1].startswith(f"{COOKIE}={RAW};")


@freeze_time(NOW)
async def test_no_request_cookie_adds_nothing():
    app = _inner_app(refresh_to=NOW + timedelta(days=30))

    assert _set_cookies(await _run(app, cookie=None)) == []


@freeze_time(NOW)
async def test_expiry_in_the_past_adds_nothing():
    app = _inner_app(refresh_to=NOW - timedelta(seconds=1))

    assert _set_cookies(await _run(app)) == []


async def test_non_http_scopes_pass_through():
    seen: list[dict] = []

    async def app(scope, receive, send):
        seen.append(scope)

    scope = {"type": "lifespan"}
    await SessionCookieRefreshMiddleware(app)(scope, None, None)

    assert seen == [scope]
