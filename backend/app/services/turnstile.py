"""Cloudflare Turnstile server-side token verification.

Disabled (no network at all) when ``TURNSTILE_ENABLED`` is false, as in dev and tests.
Never log the token or the secret.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.config import settings

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5.0

_client: httpx.AsyncClient | None = None


class TurnstileError(Exception):
    """The bot check failed. Endpoints turn this into ``detail.code``."""

    code = "auth.captcha_failed"


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
    return _client


async def aclose_client() -> None:
    """Close the shared client (app shutdown, tests)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def verify_turnstile(
    token: str | None,
    remote_ip: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Return if the token is valid (or Turnstile is off); raise ``TurnstileError`` otherwise."""
    if not settings.TURNSTILE_ENABLED:
        return

    log = structlog.get_logger(__name__)
    if not token:
        log.warning("turnstile.failed", reason="missing_token")
        raise TurnstileError()

    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        response = await (client or _get_client()).post(
            SITEVERIFY_URL, data=data, timeout=TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        log.warning("turnstile.failed", reason="request_error", error=type(exc).__name__)
        raise TurnstileError() from exc

    if not response.is_success:
        log.warning("turnstile.failed", reason="http_status", status=response.status_code)
        raise TurnstileError()

    try:
        result = response.json()
    except ValueError as exc:
        log.warning("turnstile.failed", reason="invalid_json")
        raise TurnstileError() from exc

    if not isinstance(result, dict) or result.get("success") is not True:
        error_codes = result.get("error-codes", []) if isinstance(result, dict) else []
        log.warning("turnstile.failed", reason="rejected", error_codes=error_codes)
        raise TurnstileError()
