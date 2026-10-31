"""Signed, stateless one-click unsubscribe tokens (RFC 8058) for the notification emails.

A token is ``v1.<user_id>.<preference>.<signature>``: the signature is HMAC-SHA256 with
``SECRET_KEY`` over ``uf-unsubscribe:<version>:<user_id>:<preference>`` (the prefix keeps it
apart from every other HMAC made with the same key), base64url without padding. Nothing is
stored and there is no expiry: an unsubscribe link must keep working for as long as the email
sits in someone's mailbox. The version prefix allows rotation: a ``v2`` scheme can be added
next to ``v1``; changing ``SECRET_KEY`` invalidates every issued token (the in-body link to the
account settings still works).

The token names one switchable preference (``PREFERENCES``); it never grants anything else, so
the endpoint that consumes it needs no session (``POST /api/v1/notifications/unsubscribe``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlencode

from app.core.config import settings

TOKEN_VERSION = "v1"
MAX_TOKEN_LENGTH = 200
UNSUBSCRIBE_PATH = "/notifications/unsubscribe"
PREFERENCES = frozenset(
    {
        "reply_to_my_thread",
        "comment_on_my_post",
        "reply_to_my_reply",
        "moderation_decisions",
        "admin_digest",
    }
)
_SIGNING_PREFIX = "uf-unsubscribe"


def _sign(version: str, user_id: int, preference: str) -> str:
    message = f"{_SIGNING_PREFIX}:{version}:{user_id}:{preference}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_token(user_id: int, preference: str) -> str:
    """The unsubscribe token for ``preference`` of user ``user_id``."""
    if preference not in PREFERENCES:
        raise ValueError(f"Not a switchable email preference: {preference!r}")
    signature = _sign(TOKEN_VERSION, user_id, preference)
    return f"{TOKEN_VERSION}.{user_id}.{preference}.{signature}"


def read_token(token: str) -> tuple[int, str] | None:
    """``(user_id, preference)`` from a valid token, else ``None`` (malformed, unknown version,
    bad signature, or a preference that cannot be switched off this way)."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    version, raw_id, preference, signature = parts
    if version != TOKEN_VERSION or not raw_id.isascii() or not raw_id.isdigit():
        return None
    user_id = int(raw_id)
    if not hmac.compare_digest(signature.encode(), _sign(version, user_id, preference).encode()):
        return None
    if preference not in PREFERENCES:
        return None
    return user_id, preference


def unsubscribe_url(user_id: int, preference: str) -> str:
    """Absolute URL of the one-click endpoint for this user and preference. It goes through
    ``FRONTEND_URL``: the frontend's nginx proxies ``/api/`` to the backend."""
    query = urlencode({"token": make_token(user_id, preference)})
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}{settings.API_V1_PREFIX}{UNSUBSCRIBE_PATH}?{query}"
