"""Re-send the session cookie when the session's sliding expiry moves (pure ASGI middleware).

The session expiry slides forward server-side (``crud.session.touch_session``, at most once a
day), but the browser drops the cookie when the ``Max-Age`` it got at login runs out. So when
``deps.get_current_user`` slides the expiry, it stores the new ``expires_at`` on the request
state under ``REFRESH_STATE_KEY``, and this middleware appends a ``Set-Cookie`` for the same
raw token with ``Max-Age`` = the time left until that expiry, built by Starlette's own
``set_cookie`` with ``session_cookie_params`` (same name, flags and format as at login).

It never adds the header when the response already sets the session cookie, to a new value
(login, verify-email, password reset) or by clearing it (logout, revoking the current session,
account deletion): a refresh there would undo the sign-out or put back the old token.

The refresh is sent only on successful responses (status below 400). An error response
usually means the request's transaction rolled back, touch included, so re-sending the cookie
there would let it drift from the stored expiry, and every failing request would send it again.
The rare exception is an ``AppError`` with ``keep_changes``, which commits the touch and
still answers 4xx: that slide reaches the cookie only with the next slide (a day later), so the
cookie can lag the stored expiry by up to a day. The server checks ``expires_at`` on every
request either way.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.security import session_cookie_params

# ``request.state`` attribute (a key of ``scope["state"]``): the session's new ``expires_at``.
REFRESH_STATE_KEY = "session_cookie_refresh"


def _sets_session_cookie(headers: MutableHeaders, name: str) -> bool:
    prefix = f"{name}="
    return any(value.startswith(prefix) for value in headers.getlist("set-cookie"))


def _refresh_header(raw_token: str, expires_at: datetime) -> bytes | None:
    max_age = int((expires_at - datetime.now(UTC)).total_seconds())
    if max_age <= 0:
        return None
    params = session_cookie_params(settings)
    params["max_age"] = max_age
    response = Response()
    response.set_cookie(value=raw_token, **params)
    return next(value for key, value in response.raw_headers if key == b"set-cookie")


class SessionCookieRefreshMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Make sure the state dict exists before the app runs, so ``request.state`` writes land
        # in the dict this middleware reads.
        state = scope.setdefault("state", {})

        async def send_with_refresh(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                expires_at = state.get(REFRESH_STATE_KEY)
                if expires_at is not None:
                    message.setdefault("headers", [])
                    headers = MutableHeaders(scope=message)
                    name = settings.SESSION_COOKIE_NAME
                    raw_token = HTTPConnection(scope).cookies.get(name)
                    if raw_token and not _sets_session_cookie(headers, name):
                        value = _refresh_header(raw_token, expires_at)
                        if value is not None:
                            headers.append("set-cookie", value.decode("latin-1"))
            await send(message)

        await self.app(scope, receive, send_with_refresh)
