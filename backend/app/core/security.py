"""Password hashing, password policy, opaque tokens, expiries and the session cookie.

- Passwords: argon2id via ``argon2.PasswordHasher`` with the library defaults (RFC 9106 low-memory
  profile). Verification is the library's constant-time check.
- Session and email tokens: 32 random bytes, URL-safe base64 for the client; only the SHA-256 hex
  digest is stored, so a database leak does not leak usable tokens.
- Password policy follows NIST SP 800-63B: length limits and a blocklist, no composition rules.

Never log passwords, raw tokens or hashes.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.config import settings as app_settings
from app.db.enums import TokenPurpose

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
TOKEN_BYTES = 32

TOKEN_TTLS: dict[TokenPurpose, timedelta] = {
    TokenPurpose.VERIFY_EMAIL: timedelta(hours=48),
    TokenPurpose.RESET_PASSWORD: timedelta(hours=1),
    TokenPurpose.CHANGE_EMAIL: timedelta(hours=24),
}

# Frequently breached passwords that would otherwise satisfy the length rule (all >= 10 chars).
# Compared case-insensitively. A small built-in list, not a full breach corpus.
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "0123456789",
        "1111111111",
        "1029384756",
        "1122334455",
        "1234512345",
        "1234567890",
        "12345678910",
        "123456789a",
        "1234567891",
        "12345678912",
        "123456789q",
        "123456789abc",
        "1234567890a",
        "1234567890q",
        "123123123123",
        "123qweasdzxc",
        "1q2w3e4r5t",
        "1q2w3e4r5t6y",
        "1qaz2wsx3edc",
        "2222222222",
        "5555555555",
        "6666666666",
        "7777777777",
        "8888888888",
        "9876543210",
        "987654321a",
        "999999999999",
        "a1234567890",
        "a1b2c3d4e5",
        "aaaaaaaaaa",
        "abc1234567",
        "abcd123456",
        "abcdefghij",
        "abcdefg123",
        "abcdefghijk",
        "abcdefghijkl",
        "administrator",
        "admin12345",
        "admin123456",
        "asdfghjkl1",
        "asdfghjkl;",
        "asdfasdfasdf",
        "baseball123",
        "basketball",
        "changeme123",
        "charlie123",
        "chocolate1",
        "computer123",
        "football123",
        "footballfootball",
        "iloveyou12",
        "iloveyou123",
        "iloveyou1234",
        "jennifer123",
        "letmein123",
        "letmein1234",
        "liverpool1",
        "liverpool123",
        "login12345",
        "michael123",
        "monkey12345",
        "passw0rd123",
        "password00",
        "password01",
        "password1!",
        "password12",
        "password123",
        "password1234",
        "password12345",
        "password123!",
        "password2020",
        "password2021",
        "password2022",
        "password2023",
        "password2024",
        "password2025",
        "password2026",
        "passwordpassword",
        "p@ssw0rd123",
        "princess123",
        "q1w2e3r4t5",
        "q1w2e3r4t5y6",
        "qazwsxedc1",
        "qazwsxedcrfv",
        "qwer123456",
        "qwerty1234",
        "qwerty12345",
        "qwerty123456",
        "qwertyuiop",
        "qwertyuiop1",
        "qwertyuiop123",
        "starwars123",
        "sunshine123",
        "superman123",
        "trustno1trustno1",
        "welcome123",
        "welcome1234",
        "whatever123",
        "zaq12wsxcde3",
        "zxcvbnm123",
        "zxcvbnmasdfghjkl",
        "urbanfloods",
        "urbanfloods1",
        "urbanfloods123",
    }
)

# One hasher for the process: argon2id with the library's default parameters.
_password_hasher = PasswordHasher()


class PasswordPolicyError(Exception):
    """A password failed the policy. ``code`` is the client-facing error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- passwords --------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an encoded argon2id hash (``$argon2id$...``) with a fresh random salt."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True if ``password`` matches ``password_hash``. Never raises; any failure is False."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with parameters other than the current defaults."""
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def validate_password_policy(password: str) -> None:
    """Raise ``PasswordPolicyError`` if the password is unacceptable.

    Rules (NIST SP 800-63B, no composition rules): 10–128 characters; not whitespace only
    (reported as ``auth.password_too_short``, since it is effectively empty); not in the common
    password list (case-insensitive).
    """
    if len(password) < PASSWORD_MIN_LENGTH or not password.strip():
        raise PasswordPolicyError("auth.password_too_short")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError("auth.password_too_long")
    if password.casefold() in COMMON_PASSWORDS:
        raise PasswordPolicyError("auth.password_too_common")


# --- opaque tokens ----------------------------------------------------------------------------


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest (64 chars) of a raw token; this is what is stored."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)``: 32 random bytes, URL-safe, and its SHA-256 hex."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_token(raw)


# --- expiries ---------------------------------------------------------------------------------


def session_expiry(now: datetime | None = None) -> datetime:
    """``now`` + ``SESSION_TTL_DAYS`` days (tz-aware UTC when ``now`` is omitted)."""
    return (now or _utcnow()) + timedelta(days=app_settings.SESSION_TTL_DAYS)


def token_expiry(purpose: TokenPurpose, now: datetime | None = None) -> datetime:
    """Expiry for an email token: verify 48 h, reset 1 h, change-email 24 h."""
    return (now or _utcnow()) + TOKEN_TTLS[purpose]


# --- cookie -----------------------------------------------------------------------------------


def session_cookie_params(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for ``Response.set_cookie`` (add ``value=raw_token``)."""
    return {
        "key": settings.SESSION_COOKIE_NAME,
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.SESSION_TTL_DAYS * 86400,
    }
