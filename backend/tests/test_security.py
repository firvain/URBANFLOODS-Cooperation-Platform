"""Increment 1b: password hashing, password policy, opaque tokens, expiries and cookie params.

Pure unit tests, no database.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.core.config import Settings, settings
from app.core.security import (
    PasswordPolicyError,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    session_cookie_params,
    session_expiry,
    token_expiry,
    validate_password_policy,
    verify_password,
)
from app.db.enums import TokenPurpose

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


# --- password hashing -------------------------------------------------------------------------


def test_hash_verify_round_trip():
    hashed = hash_password("correct horse battery")
    assert verify_password("correct horse battery", hashed) is True


def test_verify_wrong_password_is_false():
    hashed = hash_password("correct horse battery")
    assert verify_password("correct horse batterY", hashed) is False


@pytest.mark.parametrize(
    "bad_hash",
    ["", "not-a-hash", "$argon2id$v=19$m=65536,t=3,p=4$garbage", "$2b$12$bcryptlooking"],
)
def test_verify_malformed_hash_is_false_and_does_not_raise(bad_hash):
    assert verify_password("correct horse battery", bad_hash) is False


def test_hash_is_argon2id():
    assert hash_password("correct horse battery").startswith("$argon2id$")


def test_hashes_are_salted():
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_fresh_hash_does_not_need_rehash():
    assert password_needs_rehash(hash_password("correct horse battery")) is False


def test_weaker_params_need_rehash():
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("correct horse battery")
    assert password_needs_rehash(weak) is True
    assert verify_password("correct horse battery", weak) is True


# --- password policy --------------------------------------------------------------------------


def _policy_code(password: str) -> str | None:
    try:
        validate_password_policy(password)
    except PasswordPolicyError as exc:
        return exc.code
    return None


def test_policy_too_short():
    assert _policy_code("a" * 9) == "auth.password_too_short"


def test_policy_too_long():
    assert _policy_code("a" * 129) == "auth.password_too_long"


def test_policy_boundaries_pass():
    assert _policy_code("flood-gate") is None  # 10
    assert _policy_code("x" * 128) is None


@pytest.mark.parametrize("password", ["Password123", "password123", "QWERTYUIOP", "1234567890"])
def test_policy_too_common_case_insensitive(password):
    assert _policy_code(password) == "auth.password_too_common"


def test_policy_whitespace_only_is_too_short():
    # Decision: a whitespace-only password counts as empty, so it is reported as too short.
    assert _policy_code(" " * 10) == "auth.password_too_short"
    assert _policy_code("\t \n" * 5) == "auth.password_too_short"


def test_policy_passphrase_passes():
    assert _policy_code("correct horse battery") is None


def test_policy_has_no_composition_rules():
    assert _policy_code("alllowercaseletters") is None


def test_policy_error_is_exception_with_code():
    err = PasswordPolicyError("auth.password_too_short")
    assert isinstance(err, Exception)
    assert err.code == "auth.password_too_short"


# --- opaque tokens ----------------------------------------------------------------------------


def test_generate_token_shape():
    raw, token_hash = generate_token()
    assert len(raw) >= 43
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", raw)
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash)
    assert hash_token(raw) == token_hash


def test_generate_token_is_random():
    first, second = generate_token(), generate_token()
    assert first[0] != second[0]
    assert first[1] != second[1]


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
    # sha256("abc")
    assert hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# --- expiries ---------------------------------------------------------------------------------


def test_session_expiry_with_now():
    assert session_expiry(NOW) == NOW + timedelta(days=settings.SESSION_TTL_DAYS)


@freeze_time("2026-03-01 12:00:00")
def test_session_expiry_defaults_to_utc_now():
    expiry = session_expiry()
    assert expiry.tzinfo is not None
    assert expiry.utcoffset() == timedelta(0)
    assert expiry == NOW + timedelta(days=settings.SESSION_TTL_DAYS)


@pytest.mark.parametrize(
    ("purpose", "delta"),
    [
        (TokenPurpose.VERIFY_EMAIL, timedelta(hours=48)),
        (TokenPurpose.RESET_PASSWORD, timedelta(hours=1)),
        (TokenPurpose.CHANGE_EMAIL, timedelta(hours=24)),
    ],
)
def test_token_expiry_per_purpose(purpose, delta):
    assert token_expiry(purpose, NOW) == NOW + delta


@freeze_time("2026-03-01 12:00:00")
def test_token_expiry_defaults_to_utc_now():
    expiry = token_expiry(TokenPurpose.RESET_PASSWORD)
    assert expiry.utcoffset() == timedelta(0)
    assert expiry == NOW + timedelta(hours=1)


# --- cookie -----------------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(DATABASE_URL="postgresql+asyncpg://u:p@h/db", SECRET_KEY="s", **overrides)


def test_session_cookie_params_insecure():
    params = session_cookie_params(_settings(COOKIE_SECURE=False))
    assert params == {
        "key": "uf_session",
        "httponly": True,
        "secure": False,
        "samesite": "lax",
        "path": "/",
        "max_age": 30 * 86400,
    }


def test_session_cookie_params_secure_and_overrides():
    params = session_cookie_params(
        _settings(COOKIE_SECURE=True, SESSION_COOKIE_NAME="other", SESSION_TTL_DAYS=7)
    )
    assert params == {
        "key": "other",
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
        "max_age": 7 * 86400,
    }
