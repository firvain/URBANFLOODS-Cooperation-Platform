"""CSRF defence: a pure ASGI middleware for unsafe requests (POST, PUT, PATCH, DELETE).

The session cookie is ``SameSite=Lax``, which already keeps it off cross-site POSTs in modern
browsers. This middleware is the second layer:

1. **Origin check (every unsafe request).** The request's origin is taken from ``Origin``, or,
   if absent, from ``Referer``. If one is present it must be in the allow-list:
   ``ALLOWED_ORIGINS``, ``FRONTEND_URL`` and the request's own origin (scheme from the ASGI scope,
   or ``X-Forwarded-Proto`` when ``TRUST_PROXY_HEADERS``; host from ``Host``). Otherwise
   403 ``security.csrf_origin``. A request naming no origin at all passes this step (curl,
   server-to-server). Applying it without a cookie too stops a cross-site page from posting to
   ``/auth/login`` or ``/auth/register`` (login CSRF).
2. **Custom header (requests carrying the session cookie).** ``X-Requested-With:
   XMLHttpRequest`` is required (value case-insensitive), else 403 ``security.csrf``. HTML forms
   cannot set it and a cross-origin ``fetch`` that sets it needs a CORS preflight, which only the
   allowed origins pass. Requests without the cookie cannot act as a user, so curl-style use of
   the public endpoints works without the header.

Safe methods and the probes / API docs are never checked. Exactly one unsafe API route is exempt:
``POST /api/v1/notifications/unsubscribe`` (``UNSUBSCRIBE_PATH``), the RFC 8058 one-click
unsubscribe target. Mail clients and mail providers' servers POST to it from anywhere, without
the custom header and possibly with a foreign ``Origin`` (or, from a browser that holds a
session, the cookie). It is safe to exempt because it ignores the session entirely: it acts only
on the signed token in its URL, and the only thing a token can do is switch off the one email
preference it names for the one user it names (see ``services/unsubscribe.py``).

Rejections are logged as ``security.csrf_rejected`` (method, path, reason; never the cookie).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.exceptions import error_body

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
REQUIRED_HEADER = "x-requested-with"
REQUIRED_HEADER_VALUE = "xmlhttprequest"
UNSUBSCRIBE_PATH = f"{settings.API_V1_PREFIX}/notifications/unsubscribe"
EXEMPT_PATHS = frozenset({"/health", "/health/ready", UNSUBSCRIBE_PATH})
DOCS_PREFIX = "/docs"
_DEFAULT_PORTS = {"http": 80, "https": 443}

CSRF_CODE = "security.csrf"
CSRF_MESSAGE = "Missing or invalid X-Requested-With header."
CSRF_ORIGIN_CODE = "security.csrf_origin"
CSRF_ORIGIN_MESSAGE = "Cross-site request rejected."


def normalise_origin(value: str) -> str | None:
    """``scheme://host[:port]`` in lower case with the default port dropped, or None if
    ``value`` is not an absolute http(s) URL (``"null"``, garbage, other schemes)."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _own_origin(scope: Scope, headers: Headers) -> str | None:
    host = headers.get("host")
    if not host:
        return None
    scheme = scope.get("scheme", "http")
    if settings.TRUST_PROXY_HEADERS:
        forwarded = headers.get("x-forwarded-proto")
        if forwarded:
            scheme = forwarded.split(",")[0].strip()
    return normalise_origin(f"{scheme}://{host}")


def _allowed_origins(scope: Scope, headers: Headers) -> set[str]:
    allowed = {
        origin
        for origin in map(normalise_origin, [*settings.ALLOWED_ORIGINS, settings.FRONTEND_URL])
        if origin
    }
    own = _own_origin(scope, headers)
    if own:
        allowed.add(own)
    return allowed


def _origin_ok(scope: Scope, headers: Headers) -> bool:
    claimed = headers.get("origin")
    if claimed is None:
        claimed = headers.get("referer")
    if claimed is None:
        return True
    origin = normalise_origin(claimed)
    return origin is not None and origin in _allowed_origins(scope, headers)


def _has_session_cookie(headers: Headers) -> bool:
    cookie_header = headers.get("cookie")
    if not cookie_header:
        return False
    return bool(cookie_parser(cookie_header).get(settings.SESSION_COOKIE_NAME))


def _is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    if path == DOCS_PREFIX or path.startswith(f"{DOCS_PREFIX}/"):
        return True
    return path == f"{settings.API_V1_PREFIX}/openapi.json"


def check_csrf(scope: Scope) -> str | None:
    """The rejection code for this request, or None if it may proceed."""
    if scope["method"] not in UNSAFE_METHODS or _is_exempt(scope["path"]):
        return None
    headers = Headers(scope=scope)
    if _has_session_cookie(headers):
        if (headers.get(REQUIRED_HEADER) or "").strip().lower() != REQUIRED_HEADER_VALUE:
            return CSRF_CODE
    if not _origin_ok(scope, headers):
        return CSRF_ORIGIN_CODE
    return None


class CSRFMiddleware:
    """Pure ASGI middleware applying :func:`check_csrf`. Mount it inside ``CORSMiddleware`` so
    the browser can read the 403 body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        code = check_csrf(scope)
        if code is None:
            await self.app(scope, receive, send)
            return
        structlog.get_logger(__name__).warning(
            "security.csrf_rejected", method=scope["method"], path=scope["path"], reason=code
        )
        message = CSRF_MESSAGE if code == CSRF_CODE else CSRF_ORIGIN_MESSAGE
        response = JSONResponse(status_code=403, content=error_body(code, message))
        await response(scope, receive, send)
