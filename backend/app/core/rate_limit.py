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
store never holds more than ``MAX_KEYS`` keys, so a flood of distinct IPs cannot exhaust memory.
When a new key finds the store full, drained buckets are swept first and the least recently used
key is evicted only if the store is still full, so flooding new keys cannot evict a bucket that is
still limiting (a locked account) while drained ones exist. Residual risk: an attacker who fills
the whole store with *active* buckets can still evict one; that takes tens of thousands of client
IPs (or addresses, for the account store) within one window, each also limited per IP.

Client IPs are normalised before they become keys (``bucket_ip``): an IPv6 address counts as its
/64 network, since one subscriber usually holds a whole /64 and could otherwise take a fresh bucket
per address; an IPv4-mapped IPv6 address counts as the IPv4 address.

Per-account limits on failed password checks (a second store, ``account_store()``) stop guessing
spread over many IPs. ``LOGIN_ACCOUNT_LIMIT`` (login) and ``PASSWORD_CHECK_ACCOUNT_LIMIT``
(current-password checks: change password, change email, delete account) are separate budgets;
both key a known account by its user id (``user_account_key``), and login keys an address that
belongs to no account by a keyed hash of the normalised email (``login_account_key``), so unknown
addresses are counted like known ones and the answer does not reveal which exist. The endpoint
calls ``consume_account`` before it verifies the password, so a full bucket refuses even the
right password (counting up front also keeps concurrent guesses from slipping past the check),
and ``clear_account`` once the password proved right: only someone holding the password can
empty the bucket, and the owner's own typos after an attacker's failures do not lock them out.
Trade-off: anyone who knows an address can keep that account from signing in with a password
while they keep guessing; each refusal says to retry within 15 minutes (``Retry-After``), the
bucket drains 15 minutes after the guessing stops, and password reset by email keeps working
throughout.

Exceeding a limit answers 429 ``rate.limited`` with ``Retry-After`` (whole seconds).
``RATE_LIMIT_ENABLED=false`` turns everything off. Nothing is audited; a limited request is logged
at info with the limit name and a keyed hash of the IP or account key (never the IP or email).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
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
    # Generous per IP: NAT and venue Wi-Fi put many people behind one address (partners register
    # by QR code at meetings). Turnstile and the per-account limits are the main defence.
    ("POST", f"{_AUTH}/register"): Limit("auth.register", 30, 3600),
    ("POST", f"{_AUTH}/login"): Limit("auth.login", 60, 900),
    ("POST", f"{_AUTH}/resend-verification"): Limit("auth.resend_verification", 10, 3600),
    ("POST", f"{_AUTH}/password/forgot"): Limit("auth.password_forgot", 10, 3600),
    ("POST", f"{_AUTH}/password/reset"): Limit("auth.password_reset", 10, 3600),
    ("POST", f"{_AUTH}/email/confirm"): Limit("auth.email_confirm", 10, 3600),
    ("POST", f"{_AUTH}/me/password"): Limit("auth.me_password", 10, 3600),
    ("POST", f"{_AUTH}/me/email"): Limit("auth.me_email", 5, 3600),
    ("DELETE", f"{_AUTH}/me"): Limit("auth.me_delete", 5, 3600),
    # One-click unsubscribe: mail providers POST from shared server IPs on behalf of many
    # recipients, so the limit is per minute and generous; the token is an HMAC, so it guards
    # against write floods, not guessing.
    ("POST", f"{settings.API_V1_PREFIX}/notifications/unsubscribe"): Limit(
        "notifications.unsubscribe", 30, 60
    ),
}
DEFAULT_LIMIT = Limit("api.default", 300, 60)
# Failed password checks per account (see the module docstring for the lockout trade-off).
LOGIN_ACCOUNT_LIMIT = Limit("auth.login_account", 10, 900)
PASSWORD_CHECK_ACCOUNT_LIMIT = Limit("auth.password_check_account", 10, 3600)


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
        if stored is None and len(self._tat) >= self.max_keys:
            # Drop drained buckets before evicting one that is still limiting.
            self.sweep(now)
            while len(self._tat) >= self.max_keys:
                self._tat.popitem(last=False)
        self._tat[key] = new_tat
        return 0.0

    def forget(self, key: str) -> None:
        """Empty ``key``'s bucket (it behaves like a new key afterwards)."""
        self._tat.pop(key, None)


_store = BucketStore()
_account_store = BucketStore()


def store() -> BucketStore:
    return _store


def account_store() -> BucketStore:
    return _account_store


def reset() -> None:
    """Forget every bucket, per IP and per account (tests)."""
    _store.clear()
    _account_store.clear()


def _keyed_hash(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _ip_hash(ip: str) -> str:
    """Keyed hash for logs: correlatable within one deployment, not reversible by brute force
    over the IPv4 space like a bare sha256 would be."""
    return _keyed_hash(ip)[:12]


def bucket_ip(ip: str | None) -> str:
    """The bucket key for a client IP: IPv4 as is, IPv6 as its /64 network (e.g.
    ``2001:db8:1:2::/64``), an IPv4-mapped IPv6 address as the IPv4 address. A missing value is
    ``UNKNOWN_IP``; a value that is not an IP address is used unchanged."""
    if not ip:
        return UNKNOWN_IP
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        # Drop any zone id ("%eth0"): it names a local interface, not a network.
        unscoped = ipaddress.IPv6Address(address.packed)
        return str(ipaddress.IPv6Network((unscoped, 64), strict=False))
    return str(address)


def _retry_after(wait: float) -> int:
    return max(1, math.ceil(wait))


def _consume(limit_: Limit, ip: str | None) -> int:
    """Count a request against ``limit_``; 0 if allowed, else ``Retry-After`` seconds."""
    ip = bucket_ip(ip)
    wait = _store.hit(f"{limit_.name}|{ip}", limit_.times, limit_.seconds)
    if wait <= 0:
        return 0
    structlog.get_logger(__name__).info("rate.limited", limit=limit_.name, ip_hash=_ip_hash(ip))
    return _retry_after(wait)


def _limited_body() -> dict:
    return error_body(RATE_LIMITED_CODE, RATE_LIMITED_MESSAGE)


def _limited_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=_limited_body()["detail"],
        headers={"Retry-After": str(retry_after)},
    )


# --- per-account limits on failed password checks ---------------------------------------------


def login_account_key(email: str) -> str:
    """The account key for a login attempt with an address that belongs to no account: a keyed
    hash of the address, trimmed and lower-cased. The address itself is never kept. (A known
    account is keyed by its id, ``user_account_key``, so spellings that CITEXT treats as equal
    always share a bucket.)"""
    return "email:" + _keyed_hash(email.strip().lower())


def user_account_key(user_id: int) -> str:
    """The account key for a known account (login and current-password checks)."""
    return f"user:{user_id}"


def consume_account(limit_: Limit, account_key: str) -> None:
    """Count one password check against ``account_key`` before the password is verified; raise
    429 ``rate.limited`` (with ``Retry-After``) if the account's bucket is full. Call
    ``clear_account`` when the password turns out to be right. No-op when rate limiting is off.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    wait = _account_store.hit(f"{limit_.name}|{account_key}", limit_.times, limit_.seconds)
    if wait <= 0:
        return
    structlog.get_logger(__name__).info(
        "rate.limited", limit=limit_.name, account_hash=_keyed_hash(account_key)[:12]
    )
    raise _limited_exception(_retry_after(wait))


def clear_account(limit_: Limit, account_key: str) -> None:
    """Empty the account's bucket for ``limit_``: the password was right."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    _account_store.forget(f"{limit_.name}|{account_key}")


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
            raise _limited_exception(retry_after)

    return rate_limit_dependency
