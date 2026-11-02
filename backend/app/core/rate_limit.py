"""In-memory rate limiting, keyed by client IP and a limit name.

Single worker only (like the scheduler and the caches; see docs/PLAN.md "Known risks"). Two entry
points share one store:

- ``RateLimitMiddleware`` applies ``DEFAULT_LIMIT`` (a cheap 300/min guard) to every ``/api/``
  request and, on top, the per-route ``ROUTE_LIMITS`` (the auth endpoints and the one-click
  unsubscribe). Matching is by method and path (trailing slash ignored), so every attempt counts,
  including ones the endpoint would reject with 422, and rejected requests never open a database
  session.
- ``limit(name, times, seconds)`` is a FastAPI dependency factory for routes added later:
  ``@router.post(..., dependencies=[Depends(limit("posts.create", 10, 3600))])``.

Algorithm: GCRA (a token bucket stored as one float per key, the "theoretical arrival time").
``times`` requests may arrive in a burst; after that one more is allowed every
``seconds / times``. A key whose bucket is full again is expired and swept every minute; the
store never holds more than ``MAX_KEYS`` keys (least recently used evicted first), so a flood of
distinct IPs cannot exhaust memory.

Exceeding a limit answers 429 ``rate.limited`` with ``Retry-After`` (whole seconds).
``RATE_LIMIT_ENABLED=false`` turns everything off. Nothing is audited; a limited request is logged
at info with the limit name and a keyed hash of the IP (never the IP itself).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.deps import client_ip
from app.core.exceptions import error_body

MAX_KEYS = 50_000
SWEEP_INTERVAL_SECONDS = 60.0
RATE_LIMITED_CODE = "rate.limited"
RATE_LIMITED_MESSAGE = "Too many requests. Please try again later."
API_PATH_PREFIX = "/api/"
UNKNOWN_IP = "unknown"


@dataclass(frozen=True)
class Limit:
    name: str
    times: int
    seconds: int

    def __post_init__(self) -> None:
        if self.times < 1 or self.seconds < 1:
            raise ValueError(f"Rate limit {self.name!r} needs times >= 1 and seconds >= 1")


_AUTH = f"{settings.API_V1_PREFIX}/auth"
ROUTE_LIMITS: dict[tuple[str, str], Limit] = {
    ("POST", f"{_AUTH}/register"): Limit("auth.register", 5, 3600),
    ("POST", f"{_AUTH}/login"): Limit("auth.login", 10, 900),
    ("POST", f"{_AUTH}/resend-verification"): Limit("auth.resend_verification", 3, 3600),
    ("POST", f"{_AUTH}/password/forgot"): Limit("auth.password_forgot", 3, 3600),
    ("POST", f"{_AUTH}/password/reset"): Limit("auth.password_reset", 10, 3600),
    ("POST", f"{_AUTH}/email/confirm"): Limit("auth.email_confirm", 10, 3600),
    ("POST", f"{_AUTH}/me/password"): Limit("auth.me_password", 10, 3600),
    ("POST", f"{_AUTH}/me/email"): Limit("auth.me_email", 5, 3600),
    # One-click unsubscribe: mail providers POST from shared server IPs on behalf of many
    # recipients, so the limit is per minute and generous; the token is an HMAC, so it guards
    # against write floods, not guessing.
    ("POST", f"{settings.API_V1_PREFIX}/notifications/unsubscribe"): Limit(
        "notifications.unsubscribe", 30, 60
    ),
}
DEFAULT_LIMIT = Limit("api.default", 300, 60)


# Floating-point slack when comparing times (far below any real limit's interval).
_TOLERANCE_SECONDS = 1e-6


class BucketStore:
    """GCRA buckets: key -> theoretical arrival time, in least-recently-used order.

    Synchronous and await-free, so it is atomic on the event loop.
    """

    def __init__(
        self, *, max_keys: int = MAX_KEYS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_keys = max_keys
        self._clock = clock
        self._tat: OrderedDict[str, float] = OrderedDict()
        self._next_sweep = clock() + SWEEP_INTERVAL_SECONDS

    def __len__(self) -> int:
        return len(self._tat)

    def __contains__(self, key: object) -> bool:
        return key in self._tat

    def clear(self) -> None:
        self._tat.clear()
        self._next_sweep = self._clock() + SWEEP_INTERVAL_SECONDS

    def sweep(self, now: float | None = None) -> None:
        """Drop every key whose bucket is full again (it would behave like a new key)."""
        now = self._clock() if now is None else now
        for key in [key for key, tat in self._tat.items() if tat <= now]:
            del self._tat[key]
        self._next_sweep = now + SWEEP_INTERVAL_SECONDS

    def hit(self, key: str, times: int, seconds: float) -> float:
        """Count one request. Returns 0 if allowed, else the seconds until one would be."""
        now = self._clock()
        if now >= self._next_sweep:
            self.sweep(now)
        interval = seconds / times
        stored = self._tat.get(key)
        new_tat = max(stored if stored is not None else now, now) + interval
        allow_at = new_tat - seconds
        if stored is not None:
            self._tat.move_to_end(key)
        # ``allow_at`` is computed as ``(now + interval) - seconds``, which can round to a few ulps
        # above ``now``: a tolerance keeps that from refusing a hit that is exactly on time.
        if allow_at - now > _TOLERANCE_SECONDS:
            return allow_at - now
        if stored is None:
            while len(self._tat) >= self.max_keys:
                self._tat.popitem(last=False)
        self._tat[key] = new_tat
        return 0.0


_store = BucketStore()


def store() -> BucketStore:
    return _store


def reset() -> None:
    """Forget every bucket (tests)."""
    _store.clear()


def _ip_hash(ip: str) -> str:
    """Keyed hash for logs: correlatable within one deployment, not reversible by brute force
    over the IPv4 space like a bare sha256 would be."""
    return hmac.new(settings.SECRET_KEY.encode(), ip.encode(), hashlib.sha256).hexdigest()[:12]


def _consume(limit_: Limit, ip: str | None) -> int:
    """Count a request against ``limit_``; 0 if allowed, else ``Retry-After`` seconds."""
    ip = ip or UNKNOWN_IP
    wait = _store.hit(f"{limit_.name}|{ip}", limit_.times, limit_.seconds)
    if wait <= 0:
        return 0
    structlog.get_logger(__name__).info("rate.limited", limit=limit_.name, ip_hash=_ip_hash(ip))
    return max(1, math.ceil(wait))


def _limited_body() -> dict:
    return error_body(RATE_LIMITED_CODE, RATE_LIMITED_MESSAGE)


def _limits_for(method: str, path: str) -> list[Limit]:
    if not path.startswith(API_PATH_PREFIX):
        return []
    limits = [DEFAULT_LIMIT]
    route = ROUTE_LIMITS.get((method, path.rstrip("/") or "/"))
    if route is not None:
        limits.append(route)
    return limits


class RateLimitMiddleware:
    """Pure ASGI middleware applying ``DEFAULT_LIMIT`` and ``ROUTE_LIMITS``. Mount it inside
    ``CORSMiddleware`` (so the SPA can read the 429) and outside ``CSRFMiddleware`` (so rejected
    cross-site attempts count too)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return
        limits = _limits_for(scope["method"], scope["path"])
        if limits:
            ip = client_ip(Request(scope))
            for limit_ in limits:
                retry_after = _consume(limit_, ip)
                if retry_after:
                    response = JSONResponse(
                        status_code=429,
                        content=_limited_body(),
                        headers={"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def limit(name: str, times: int, seconds: int) -> Callable[[Request], Awaitable[None]]:
    """A FastAPI dependency enforcing ``times`` requests per ``seconds`` per client IP:
    ``dependencies=[Depends(limit("posts.create", 10, 3600))]``."""
    limit_ = Limit(name, times, seconds)

    async def rate_limit_dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        retry_after = _consume(limit_, client_ip(request))
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail=_limited_body()["detail"],
                headers={"Retry-After": str(retry_after)},
            )

    return rate_limit_dependency
