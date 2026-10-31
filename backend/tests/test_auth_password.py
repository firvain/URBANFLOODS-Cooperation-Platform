"""Increment 1f: password forgot/reset, change password, change email (request + confirm).

The ``client`` runs the app with its own sessions and commits through ``get_db_tx``, so rows it
writes are visible to ``db_session`` and are removed by ``cleanup_users``. Users the test creates
directly are committed and registered for cleanup; so is every new address a test moves a user
to (``cleanup_users`` deletes by email).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.crud.token import create_email_token
from app.db.enums import TokenPurpose
from app.db.models import AuditLog, EmailToken, User
from app.services.email import get_backend
from tests.factories import (
    DEFAULT_PASSWORD,
    create_user,
    create_verified_user,
    login_as,
    unique_email,
)

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
ME = f"{API}/auth/me"
FORGOT = f"{API}/auth/password/forgot"
RESET = f"{API}/auth/password/reset"
CHANGE_PASSWORD = f"{API}/auth/me/password"
CHANGE_EMAIL = f"{API}/auth/me/email"
CONFIRM_EMAIL = f"{API}/auth/email/confirm"
COOKIE = settings.SESSION_COOKIE_NAME

NEW_PASSWORD = "estuary-levee-monsoon-77"
RESET_LINK_RE = re.compile(r"/reset-password\?token=([A-Za-z0-9_\-]+)")
CONFIRM_LINK_RE = re.compile(r"/confirm-email\?token=([A-Za-z0-9_\-]+)")
RESET_SENT = {
    "code": "auth.password_reset_sent",
    "message": "If an account exists for this address, a password reset email has been sent.",
}


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _reload_user(db, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _tokens(db, user_id: int, purpose: TokenPurpose) -> list[EmailToken]:
    stmt = (
        select(EmailToken)
        .where(EmailToken.user_id == user_id, EmailToken.purpose == purpose)
        .order_by(EmailToken.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _audit(db, user_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


async def _login(client, email: str, password: str = DEFAULT_PASSWORD):
    return await client.post(LOGIN, json={"email": email, "password": password})


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_validation(response, field: str, code: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail
    if code is not None:
        assert detail["fields"][field] == code


def _link_token(message, pattern: re.Pattern[str]) -> str:
    match = pattern.search(message.text)
    assert match, "no link in the email"
    return match.group(1)


async def _request_reset(client, outbox, email: str) -> str:
    """``POST /password/forgot`` and return the raw token from the newest email."""
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 202, response.text
    return _link_token(outbox[-1], RESET_LINK_RE)


async def _request_email_change(client, outbox, new_email: str) -> str:
    """``POST /me/email`` (signed in on ``client``) and return the raw confirm token."""
    response = await client.post(
        CHANGE_EMAIL, json={"new_email": new_email, "current_password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 202, response.text
    return _link_token(outbox[-1], CONFIRM_LINK_RE)


# --- forgot password --------------------------------------------------------------------------


async def test_forgot_password_known_user(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)

    response = await client.post(FORGOT, json={"email": user.email.upper()})

    assert response.status_code == 202, response.text
    assert response.json() == RESET_SENT
    assert len(outbox) == 1
    message = outbox[0]
    assert message.to == user.email
    assert "/reset-password?token=" in message.text
    assert "Test User" in message.text
    assert message.list_unsubscribe is None

    (token,) = await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD)
    assert token.used_at is None
    (entry,) = await _audit(db_session, user.id, "auth.password_reset_requested")
    assert entry.actor_id == user.id
    assert user.email not in str(entry.metadata_)


async def test_forgot_password_unknown_email_identical_response(
    client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    known = await client.post(FORGOT, json={"email": user.email})
    outbox.clear()

    unknown = await client.post(FORGOT, json={"email": unique_email("nobody")})

    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == RESET_SENT
    assert outbox == []


@pytest.mark.parametrize("state", ["inactive", "deleted"])
async def test_forgot_password_disabled_user_sends_nothing(
    client, db_session, outbox, cleanup_users, state
):
    fields = {"is_active": False} if state == "inactive" else {"deleted_at": datetime.now(UTC)}
    user = await _committed(db_session, cleanup_users, **fields)

    response = await client.post(FORGOT, json={"email": user.email})

    assert response.status_code == 202
    assert response.json() == RESET_SENT
    assert outbox == []
    assert await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD) == []
    assert await _audit(db_session, user.id, "auth.password_reset_requested") == []


async def test_forgot_password_unverified_user_gets_email(
    client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users, factory=create_user)

    response = await client.post(FORGOT, json={"email": user.email})

    assert response.status_code == 202
    assert len(outbox) == 1
    assert outbox[0].to == user.email
    assert RESET_LINK_RE.search(outbox[0].text)


async def test_forgot_password_turnstile_failure(
    client, db_session, outbox, cleanup_users, monkeypatch
):
    user = await _committed(db_session, cleanup_users)
    monkeypatch.setattr(settings, "TURNSTILE_ENABLED", True)

    response = await client.post(FORGOT, json={"email": user.email})

    _assert_error(response, 400, "auth.captcha_failed")
    assert outbox == []
    assert await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD) == []


async def test_forgot_password_invalid_email_is_validation_error(client, outbox):
    response = await client.post(FORGOT, json={"email": "not-an-email"})
    _assert_validation(response, "email")
    assert outbox == []


async def test_forgot_password_survives_email_backend_failure(
    client, db_session, outbox, cleanup_users, monkeypatch
):
    user = await _committed(db_session, cleanup_users)
    monkeypatch.setattr(get_backend(), "send", AsyncMock(side_effect=OSError("smtp down")))

    response = await client.post(FORGOT, json={"email": user.email})

    assert response.status_code == 202
    assert response.json() == RESET_SENT


async def test_forgot_password_new_request_invalidates_older_link(
    client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    first = await _request_reset(client, outbox, user.email)
    second = await _request_reset(client, outbox, user.email)

    stale = await client.post(RESET, json={"token": first, "password": NEW_PASSWORD})
    fresh = await client.post(RESET, json={"token": second, "password": NEW_PASSWORD})

    _assert_error(stale, 400, "auth.token_invalid")
    assert fresh.status_code == 200, fresh.text


# --- reset password ---------------------------------------------------------------------------


async def test_reset_password_happy_path(client, other_client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(other_client, user)
    raw = await _request_reset(client, outbox, user.email)

    response = await client.post(
        RESET, json={"token": raw, "password": NEW_PASSWORD}, headers={"User-Agent": "Reset/1.0"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == user.id
    assert body["email"] == user.email
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert COOKIE in client.cookies

    # This browser is signed in with the new session; the other device was signed out.
    assert (await client.get(ME)).status_code == 200
    _assert_error(await other_client.get(ME), 401, "auth.not_authenticated")

    _assert_error(await _login(other_client, user.email), 401, "auth.invalid_credentials")
    assert (await _login(other_client, user.email, NEW_PASSWORD)).status_code == 200

    (token,) = await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD)
    assert token.used_at is not None
    (entry,) = await _audit(db_session, user.id, "auth.password_reset")
    assert entry.actor_id == user.id
    assert "password" not in str(entry.metadata_)


async def test_reset_password_token_is_single_use(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    raw = await _request_reset(client, outbox, user.email)

    first = await client.post(RESET, json={"token": raw, "password": NEW_PASSWORD})
    second = await client.post(RESET, json={"token": raw, "password": "another-good-password-9"})

    assert first.status_code == 200, first.text
    _assert_error(second, 400, "auth.token_invalid")
    assert (await _login(client, user.email, NEW_PASSWORD)).status_code == 200


async def test_reset_password_expired_token(client, db_session, cleanup_users):
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=long_ago
    )
    await db_session.commit()

    response = await client.post(RESET, json={"token": raw, "password": NEW_PASSWORD})

    _assert_error(response, 400, "auth.token_invalid")
    assert (await _login(client, user.email)).status_code == 200


async def test_reset_password_rejects_other_purpose_token(client, db_session, cleanup_users):
    user = await create_user(db_session)
    cleanup_users.add(user.email)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await db_session.commit()

    response = await client.post(RESET, json={"token": raw, "password": NEW_PASSWORD})

    _assert_error(response, 400, "auth.token_invalid")
    (token,) = await _tokens(db_session, user.id, TokenPurpose.VERIFY_EMAIL)
    assert token.used_at is None


async def test_reset_password_unknown_token(client):
    response = await client.post(RESET, json={"token": "x" * 43, "password": NEW_PASSWORD})
    _assert_error(response, 400, "auth.token_invalid")


@pytest.mark.parametrize("token", ["", "x" * 513])
async def test_reset_password_token_length_is_validated(client, token):
    response = await client.post(RESET, json={"token": token, "password": NEW_PASSWORD})
    _assert_validation(response, "token")


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("short", "auth.password_too_short"),
        ("password123", "auth.password_too_common"),
        ("x" * 129, "auth.password_too_long"),
    ],
)
async def test_reset_password_weak_password(
    client, db_session, outbox, cleanup_users, password, code
):
    user = await _committed(db_session, cleanup_users)
    raw = await _request_reset(client, outbox, user.email)

    response = await client.post(RESET, json={"token": raw, "password": password})

    _assert_validation(response, "password", code)
    assert COOKIE not in client.cookies
    # Rolled back: the link still works and the old password is unchanged.
    (token,) = await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD)
    assert token.used_at is None
    assert (await _login(client, user.email)).status_code == 200


async def test_reset_password_verifies_unverified_user(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users, factory=create_user)
    raw = await _request_reset(client, outbox, user.email)

    response = await client.post(RESET, json={"token": raw, "password": NEW_PASSWORD})

    assert response.status_code == 200, response.text
    assert response.json()["is_verified"] is True
    assert (await _reload_user(db_session, user.id)).is_verified is True


async def test_reset_password_disabled_user(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    raw = await _request_reset(client, outbox, user.email)
    db_user = await _reload_user(db_session, user.id)
    db_user.is_active = False
    await db_session.commit()

    response = await client.post(RESET, json={"token": raw, "password": NEW_PASSWORD})

    _assert_error(response, 403, "auth.account_disabled")
    assert "set-cookie" not in response.headers
    (token,) = await _tokens(db_session, user.id, TokenPurpose.RESET_PASSWORD)
    assert token.used_at is None
    assert await _audit(db_session, user.id, "auth.password_reset") == []


async def test_reset_password_cancels_pending_email_change(
    client, other_client, db_session, outbox, cleanup_users
):
    """Someone who had a session cannot keep a pending email change alive past a reset."""
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("attacker")
    cleanup_users.add(new_email)
    await login_as(other_client, user)
    confirm_raw = await _request_email_change(other_client, outbox, new_email)
    reset_raw = await _request_reset(client, outbox, user.email)

    assert (
        await client.post(RESET, json={"token": reset_raw, "password": NEW_PASSWORD})
    ).status_code == 200
    response = await client.post(CONFIRM_EMAIL, json={"token": confirm_raw})

    _assert_error(response, 400, "auth.token_invalid")
    assert (await _reload_user(db_session, user.id)).email == user.email


# --- change password --------------------------------------------------------------------------


def _change_password_body(current: str = DEFAULT_PASSWORD, new: str = NEW_PASSWORD) -> dict:
    return {"current_password": current, "new_password": new}


async def test_change_password_requires_login(client):
    response = await client.post(CHANGE_PASSWORD, json=_change_password_body())
    _assert_error(response, 401, "auth.not_authenticated")


async def test_change_password_wrong_current(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(
        CHANGE_PASSWORD, json=_change_password_body(current="not-the-right-password")
    )

    _assert_error(response, 400, "auth.invalid_credentials")
    (entry,) = await _audit(db_session, user.id, "auth.password_change_failed")
    assert entry.actor_id == user.id
    assert await _audit(db_session, user.id, "auth.password_changed") == []
    assert (await _login(client, user.email)).status_code == 200


async def test_change_password_same_as_current(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(CHANGE_PASSWORD, json=_change_password_body(new=DEFAULT_PASSWORD))

    _assert_validation(response, "new_password", "auth.password_same")


@pytest.mark.parametrize(
    ("password", "code"),
    [("short", "auth.password_too_short"), ("qwertyuiop", "auth.password_too_common")],
)
async def test_change_password_weak(client, db_session, cleanup_users, password, code):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(CHANGE_PASSWORD, json=_change_password_body(new=password))

    _assert_validation(response, "new_password", code)
    assert (await _login(client, user.email)).status_code == 200


async def test_change_password_body_limits(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(CHANGE_PASSWORD, json={"current_password": "", "new_password": ""})

    _assert_validation(response, "current_password")
    assert "new_password" in response.json()["detail"]["fields"]


async def test_change_password_success(client, other_client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(other_client, user)
    await login_as(client, user)

    response = await client.post(CHANGE_PASSWORD, json=_change_password_body())

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert (await client.get(ME)).status_code == 200
    _assert_error(await other_client.get(ME), 401, "auth.not_authenticated")
    _assert_error(await _login(other_client, user.email), 401, "auth.invalid_credentials")
    assert (await _login(other_client, user.email, NEW_PASSWORD)).status_code == 200

    (entry,) = await _audit(db_session, user.id, "auth.password_changed")
    assert entry.actor_id == user.id
    assert "password" not in str(entry.metadata_).replace("password_changed", "")


async def test_change_password_cancels_pending_email_change(
    client, other_client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("attacker")
    cleanup_users.add(new_email)
    await login_as(other_client, user)
    confirm_raw = await _request_email_change(other_client, outbox, new_email)
    await login_as(client, user)

    assert (await client.post(CHANGE_PASSWORD, json=_change_password_body())).status_code == 204
    response = await client.post(CONFIRM_EMAIL, json={"token": confirm_raw})

    _assert_error(response, 400, "auth.token_invalid")
    assert (await _reload_user(db_session, user.id)).email == user.email


# --- change email: request --------------------------------------------------------------------


def _change_email_body(new_email: str, password: str = DEFAULT_PASSWORD) -> dict:
    return {"new_email": new_email, "current_password": password}


async def test_change_email_requires_login(client):
    response = await client.post(CHANGE_EMAIL, json=_change_email_body(unique_email()))
    _assert_error(response, 401, "auth.not_authenticated")


async def test_change_email_wrong_password(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(
        CHANGE_EMAIL, json=_change_email_body(unique_email(), "not-the-right-password")
    )

    _assert_error(response, 400, "auth.invalid_credentials")
    assert outbox == []
    assert await _tokens(db_session, user.id, TokenPurpose.CHANGE_EMAIL) == []


async def test_change_email_same_as_current(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(CHANGE_EMAIL, json=_change_email_body(user.email.upper()))

    _assert_validation(response, "new_email", "auth.email_same")
    assert outbox == []


async def test_change_email_invalid_address(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(CHANGE_EMAIL, json=_change_email_body("not-an-email"))

    _assert_validation(response, "new_email")


async def test_change_email_taken_by_another_user(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    free = await client.post(CHANGE_EMAIL, json=_change_email_body(unique_email("free")))
    outbox.clear()

    response = await client.post(CHANGE_EMAIL, json=_change_email_body(other.email.upper()))

    assert response.status_code == 202, response.text
    assert response.json() == free.json()
    assert outbox == []
    (entry,) = await _audit(db_session, user.id, "auth.email_change_blocked")
    assert entry.actor_id == user.id
    assert other.email not in str(entry.metadata_)
    # Only the earlier (free address) token exists.
    tokens = await _tokens(db_session, user.id, TokenPurpose.CHANGE_EMAIL)
    assert [t.new_email for t in tokens] != [other.email]
    assert all(t.new_email != other.email for t in tokens)


async def test_change_email_request_success(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    await login_as(client, user)

    response = await client.post(CHANGE_EMAIL, json=_change_email_body(new_email))

    assert response.status_code == 202, response.text
    assert response.json()["code"] == "auth.email_change_sent"
    assert len(outbox) == 1
    message = outbox[0]
    assert message.to == new_email
    assert "/confirm-email?token=" in message.text
    assert new_email in message.text
    assert user.email in message.text
    assert user.email in message.html

    (token,) = await _tokens(db_session, user.id, TokenPurpose.CHANGE_EMAIL)
    assert token.new_email == new_email
    assert token.used_at is None
    # Nothing changes until the new address is confirmed.
    assert (await _reload_user(db_session, user.id)).email == user.email

    (entry,) = await _audit(db_session, user.id, "auth.email_change_requested")
    assert entry.actor_id == user.id
    assert user.email not in str(entry.metadata_)
    assert new_email not in str(entry.metadata_)


# --- change email: confirm --------------------------------------------------------------------


async def test_confirm_email_change(client, other_client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    await login_as(client, user)
    raw = await _request_email_change(client, outbox, new_email)

    # Public endpoint: the link may be opened in another browser without a session.
    response = await other_client.post(CONFIRM_EMAIL, json={"token": raw})

    assert response.status_code == 200, response.text
    assert response.json()["email"] == new_email
    assert "set-cookie" not in response.headers
    me = await client.get(ME)
    assert me.status_code == 200  # sessions are kept
    assert me.json()["email"] == new_email

    _assert_error(await _login(other_client, user.email), 401, "auth.invalid_credentials")
    assert (await _login(other_client, new_email)).status_code == 200

    (entry,) = await _audit(db_session, user.id, "auth.email_changed")
    assert entry.actor_id == user.id
    assert user.email not in str(entry.metadata_)
    assert new_email not in str(entry.metadata_)


async def test_confirm_email_change_twice(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    await login_as(client, user)
    raw = await _request_email_change(client, outbox, new_email)

    first = await client.post(CONFIRM_EMAIL, json={"token": raw})
    second = await client.post(CONFIRM_EMAIL, json={"token": raw})

    assert first.status_code == 200, first.text
    _assert_error(second, 400, "auth.token_invalid")


async def test_confirm_email_change_address_taken_meanwhile(
    client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("contested")
    await login_as(client, user)
    raw = await _request_email_change(client, outbox, new_email)
    await _committed(db_session, cleanup_users, email=new_email.upper())

    response = await client.post(CONFIRM_EMAIL, json={"token": raw})

    _assert_error(response, 409, "auth.email_taken")
    assert (await _reload_user(db_session, user.id)).email == user.email
    (token,) = await _tokens(db_session, user.id, TokenPurpose.CHANGE_EMAIL)
    assert token.used_at is None


async def test_confirm_email_change_invalid_token(client):
    response = await client.post(CONFIRM_EMAIL, json={"token": "x" * 43})
    _assert_error(response, 400, "auth.token_invalid")


async def test_confirm_email_change_empty_token(client):
    response = await client.post(CONFIRM_EMAIL, json={"token": ""})
    _assert_validation(response, "token")


async def test_confirm_email_change_rejects_reset_token(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    raw = await _request_reset(client, outbox, user.email)

    response = await client.post(CONFIRM_EMAIL, json={"token": raw})

    _assert_error(response, 400, "auth.token_invalid")


async def test_confirm_email_change_verifies_unverified_user(
    client, db_session, outbox, cleanup_users
):
    user = await _committed(db_session, cleanup_users, factory=create_user)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    await login_as(client, user)
    raw = await _request_email_change(client, outbox, new_email)

    response = await client.post(CONFIRM_EMAIL, json={"token": raw})

    assert response.status_code == 200, response.text
    assert response.json()["is_verified"] is True


async def test_confirm_email_change_disabled_user(client, db_session, outbox, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    await login_as(client, user)
    raw = await _request_email_change(client, outbox, new_email)
    db_user = await _reload_user(db_session, user.id)
    db_user.is_active = False
    await db_session.commit()

    response = await client.post(CONFIRM_EMAIL, json={"token": raw})

    _assert_error(response, 403, "auth.account_disabled")
    assert (await _reload_user(db_session, user.id)).email == user.email


async def test_confirm_email_change_invalidates_links_sent_to_old_address(
    client, db_session, outbox, cleanup_users
):
    """A reset link mailed to the old address stops working once the address has changed."""
    user = await _committed(db_session, cleanup_users)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    reset_raw = await _request_reset(client, outbox, user.email)
    await login_as(client, user)
    confirm_raw = await _request_email_change(client, outbox, new_email)

    assert (await client.post(CONFIRM_EMAIL, json={"token": confirm_raw})).status_code == 200
    response = await client.post(RESET, json={"token": reset_raw, "password": NEW_PASSWORD})

    _assert_error(response, 400, "auth.token_invalid")


async def test_confirm_email_change_invalidates_pending_verification(
    client, db_session, outbox, cleanup_users
):
    """A verification link mailed to the old address cannot verify the new one."""
    user = await _committed(db_session, cleanup_users, factory=create_user)
    new_email = unique_email("new")
    cleanup_users.add(new_email)
    _, verify_raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await db_session.commit()
    await login_as(client, user)
    confirm_raw = await _request_email_change(client, outbox, new_email)

    assert (await client.post(CONFIRM_EMAIL, json={"token": confirm_raw})).status_code == 200

    (token,) = await _tokens(db_session, user.id, TokenPurpose.VERIFY_EMAIL)
    assert token.used_at is not None
    response = await client.post(f"{API}/auth/verify-email", json={"token": verify_raw})
    _assert_error(response, 400, "auth.token_invalid")
