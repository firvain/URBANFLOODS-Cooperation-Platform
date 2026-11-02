"""Increment 1d: registration, email verification, resend verification, uniform error format.

The ``client`` runs the app with its own sessions and commits through ``get_db_tx``, so rows it
writes are visible to ``db_session`` and are removed by ``cleanup_users``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import generate_token, token_expiry
from app.crud.token import consume_email_token, create_email_token
from app.db.enums import TokenPurpose
from app.db.models import (
    AuditLog,
    EmailToken,
    NotificationPreference,
    Organisation,
    Session,
    User,
)
from app.services.email import get_backend
from tests.factories import create_user, create_verified_user, login_as, unique_email

API = settings.API_V1_PREFIX
REGISTER = f"{API}/auth/register"
VERIFY = f"{API}/auth/verify-email"
RESEND = f"{API}/auth/resend-verification"
STRONG_PASSWORD = "flood-plain-river-delta-42"
TOKEN_RE = re.compile(r"/verify-email\?token=([A-Za-z0-9_\-]+)")


def _payload(email: str, **overrides) -> dict:
    body = {
        "email": email,
        "password": STRONG_PASSWORD,
        "display_name": "Maria Papadopoulou",
        "country": "gr",
        "locale": "en",
        "accept_terms": True,
    }
    body.update(overrides)
    return body


async def _user(db, email: str) -> User | None:
    stmt = select(User).where(User.email == email).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _audit_actions(db, user_id: int) -> list[str]:
    stmt = (
        select(AuditLog.action)
        .where(AuditLog.target_type == "user", AuditLog.target_id == user_id)
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


async def _uowm_id(db) -> int:
    return await db.scalar(select(Organisation.id).where(Organisation.short_name == "UOWM"))


def _token_from(message) -> str:
    match = TOKEN_RE.search(message.text)
    assert match, "no verification link in the email"
    return match.group(1)


async def _register(client, cleanup_users, email: str | None = None, **overrides):
    email = email or unique_email("reg")
    cleanup_users.add(email)
    return email, await client.post(REGISTER, json=_payload(email, **overrides))


def _assert_validation(response, field: str, code: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail
    if code is not None:
        assert detail["fields"][field] == code


# --- register ---------------------------------------------------------------------------------


async def test_register_happy_path(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email
    assert body["display_name"] == "Maria Papadopoulou"
    assert body["is_verified"] is False
    assert isinstance(body["id"], int)
    assert "password" not in response.text and "password_hash" not in body

    user = await _user(db_session, email)
    assert user is not None
    assert user.id == body["id"]
    assert user.is_verified is False
    assert user.password_hash.startswith("$argon2id$")
    assert user.country == "GR"
    assert user.locale == "en"
    prefs = await db_session.get(NotificationPreference, user.id)
    assert prefs is not None
    # Owner decision 2026-10-31: member notifications are opt-in; the admin digest stays on.
    assert prefs.reply_to_my_thread is False
    assert prefs.comment_on_my_post is False
    assert prefs.reply_to_my_reply is False
    assert prefs.moderation_decisions is False
    assert prefs.admin_digest is True
    assert prefs.digest_frequency.value == "daily"

    assert len(outbox) == 1
    message = outbox[0]
    assert message.to == email
    assert message.locale == "en"
    assert "/verify-email?token=" in message.text
    link = re.search(r"\S*/verify-email\?token=\S+", message.text).group(0)
    assert link.startswith(settings.FRONTEND_URL)
    # Account emails cannot be switched off: no List-Unsubscribe header.
    assert message.list_unsubscribe is None

    assert await _audit_actions(db_session, user.id) == ["auth.register", "auth.consent"]
    consent = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.target_id == user.id,
            AuditLog.target_type == "user",
            AuditLog.action == "auth.consent",
        )
    )
    assert consent.metadata_ == {"terms_version": "v1", "accepted": True}
    assert consent.actor_id == user.id


async def test_register_greek_locale_sends_greek_email(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users, locale="el")

    assert response.status_code == 201, response.text
    assert len(outbox) == 1
    assert outbox[0].locale == "el"
    assert outbox[0].subject.startswith("Επιβεβαιώστε")
    assert (await _user(db_session, email)).locale == "el"


async def test_register_duplicate_email_any_case(client, outbox, cleanup_users):
    email, first = await _register(client, cleanup_users)
    assert first.status_code == 201

    _, second = await _register(client, cleanup_users, email=email.upper())

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "auth.email_taken"
    assert "message" in second.json()["detail"]
    assert len(outbox) == 1


@pytest.mark.parametrize(
    ("password", "code"),
    [("password123", "auth.password_too_common"), ("short", "auth.password_too_short")],
)
async def test_register_weak_password(client, db_session, outbox, cleanup_users, password, code):
    email, response = await _register(client, cleanup_users, password=password)

    _assert_validation(response, "password", code)
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_requires_accepting_terms(client, db_session, cleanup_users):
    email, response = await _register(client, cleanup_users, accept_terms=False)

    _assert_validation(response, "accept_terms", "must_accept")
    assert await _user(db_session, email) is None


async def test_register_invalid_email(client, cleanup_users):
    _, response = await _register(client, cleanup_users, email="not-an-email")
    _assert_validation(response, "email")


async def test_register_rejects_both_organisation_and_other(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    email, response = await _register(
        client, cleanup_users, organisation_id=uowm_id, organisation_other="Town hall"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation.failed"
    assert await _user(db_session, email) is None


async def test_register_unknown_organisation(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users, organisation_id=999_999)

    _assert_validation(response, "organisation_id", "not_found")
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_with_partner_organisation(client, db_session, outbox, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    assert uowm_id is not None

    email, response = await _register(client, cleanup_users, organisation_id=uowm_id)

    assert response.status_code == 201, response.text
    assert (await _user(db_session, email)).organisation_id == uowm_id


async def test_register_with_other_organisation(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users, organisation_other="  Town hall  ")

    assert response.status_code == 201, response.text
    user = await _user(db_session, email)
    assert user.organisation_id is None
    assert user.organisation_other == "Town hall"


async def test_register_unsupported_locale(client, cleanup_users):
    _, response = await _register(client, cleanup_users, locale="de")
    _assert_validation(response, "locale")


@pytest.mark.parametrize("country", ["GRC", "1A", "G"])
async def test_register_invalid_country(client, cleanup_users, country):
    _, response = await _register(client, cleanup_users, country=country)
    _assert_validation(response, "country")


@pytest.mark.parametrize("name", ["", " x ", "y" * 121])
async def test_register_display_name_length(client, cleanup_users, name):
    _, response = await _register(client, cleanup_users, display_name=name)
    _assert_validation(response, "display_name")


async def test_register_turnstile_failure(client, db_session, outbox, cleanup_users, monkeypatch):
    monkeypatch.setattr(settings, "TURNSTILE_ENABLED", True)

    email, response = await _register(client, cleanup_users, turnstile_token=None)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "auth.captcha_failed"
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_survives_email_backend_failure(
    client, db_session, outbox, cleanup_users, monkeypatch
):
    monkeypatch.setattr(get_backend(), "send", AsyncMock(side_effect=OSError("smtp down")))

    email, response = await _register(client, cleanup_users)

    assert response.status_code == 201, response.text
    user = await _user(db_session, email)
    assert user is not None
    assert user.is_verified is False


# --- verify email -----------------------------------------------------------------------------


async def test_verify_email_happy_path(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users)
    assert response.status_code == 201
    raw = _token_from(outbox[0])

    response = await client.post(VERIFY, json={"token": raw}, headers={"User-Agent": "Test/1.0"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == email
    assert body["is_verified"] is True
    assert body["is_trusted"] is False
    assert body["trusted_at"] is None
    assert body["role"] == "member"
    assert body["country"] == "GR"
    assert body["organisation"] is None
    assert "password_hash" not in body

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{settings.SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Path=/" in cookie
    assert "secure" not in cookie.lower()

    user = await _user(db_session, email)
    assert user.is_verified is True
    sessions = (await db_session.scalars(select(Session).where(Session.user_id == user.id))).all()
    assert len(sessions) == 1
    assert sessions[0].user_agent == "Test/1.0"

    # Verifying sends no email at all (the welcome email was removed on 2026-10-31): the only
    # message is the verification link itself.
    assert len(outbox) == 1
    assert "auth.email_verified" in await _audit_actions(db_session, user.id)


async def test_verify_email_sends_no_email(client, db_session, outbox, cleanup_users):
    _, response = await _register(client, cleanup_users)
    assert response.status_code == 201
    raw = _token_from(outbox[0])
    outbox.clear()

    response = await client.post(VERIFY, json={"token": raw})

    assert response.status_code == 200, response.text
    assert response.json()["is_verified"] is True
    assert outbox == []


async def test_verify_email_with_organisation_returns_summary(
    client, db_session, outbox, cleanup_users
):
    uowm_id = await _uowm_id(db_session)
    _, response = await _register(client, cleanup_users, organisation_id=uowm_id)
    assert response.status_code == 201

    response = await client.post(VERIFY, json={"token": _token_from(outbox[0])})

    assert response.status_code == 200, response.text
    organisation = response.json()["organisation"]
    assert organisation["id"] == uowm_id
    assert organisation["short_name"] == "UOWM"
    assert organisation["country"] == "GR"
    assert organisation["type"] == "PP"


async def test_verify_email_token_is_single_use(client, outbox, cleanup_users):
    await _register(client, cleanup_users)
    raw = _token_from(outbox[0])
    assert (await client.post(VERIFY, json={"token": raw})).status_code == 200

    again = await client.post(VERIFY, json={"token": raw})

    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "auth.token_invalid"
    assert "set-cookie" not in again.headers


async def test_verify_email_garbage_token(client):
    response = await client.post(VERIFY, json={"token": "not-a-real-token"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "auth.token_invalid"


async def test_verify_email_empty_token_is_validation_error(client):
    response = await client.post(VERIFY, json={"token": ""})
    _assert_validation(response, "token")


async def test_verify_email_expired_token(client, db_session, cleanup_users):
    user = await create_user(db_session)
    cleanup_users.add(user.email)
    long_ago = datetime.now(UTC) - timedelta(days=30)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=long_ago
    )
    await db_session.commit()

    response = await client.post(VERIFY, json={"token": raw})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "auth.token_invalid"
    assert (await _user(db_session, user.email)).is_verified is False


async def test_verify_email_deactivated_user(client, db_session, outbox, cleanup_users):
    user = await create_user(db_session, is_active=False)
    cleanup_users.add(user.email)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await db_session.commit()

    response = await client.post(VERIFY, json={"token": raw})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "auth.account_disabled"
    assert "set-cookie" not in response.headers
    assert (await _user(db_session, user.email)).is_verified is False
    count = await db_session.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == user.id)
    )
    assert count == 0
    assert outbox == []


async def _verification_token(db, user_id: int) -> tuple[EmailToken, str]:
    """A VERIFY_EMAIL token inserted directly, without invalidating the user's other ones (as
    ``create_email_token`` would), like two links issued at the same moment."""
    raw, token_hash = generate_token()
    now = datetime.now(UTC)
    token = EmailToken(
        user_id=user_id,
        purpose=TokenPurpose.VERIFY_EMAIL,
        token_hash=token_hash,
        created_at=now,
        expires_at=token_expiry(TokenPurpose.VERIFY_EMAIL, now),
    )
    db.add(token)
    await db.flush()
    return token, raw


async def _session_count(db, user_id: int, *, active_only: bool = False) -> int:
    stmt = select(func.count()).select_from(Session).where(Session.user_id == user_id)
    if active_only:
        stmt = stmt.where(Session.revoked_at.is_(None))
    return await db.scalar(stmt)


async def test_verify_email_already_verified_user_is_not_signed_in(
    client, db_session, outbox, cleanup_users
):
    """A verification link of an account that is already verified does not sign anyone in."""
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await db_session.commit()

    response = await client.post(VERIFY, json={"token": raw})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "auth.already_verified",
        "message": "This address is already verified.",
    }
    assert "set-cookie" not in response.headers
    assert settings.SESSION_COOKIE_NAME not in client.cookies
    assert await _session_count(db_session, user.id) == 0
    assert outbox == []
    # The token was spent: the second try is an ordinary invalid link.
    again = await client.post(VERIFY, json={"token": raw})
    assert again.json()["detail"]["code"] == "auth.token_invalid"


async def test_verify_email_already_verified_leaves_existing_session_alone(
    client, db_session, cleanup_users
):
    user = await create_verified_user(db_session)
    other = await create_verified_user(db_session)
    cleanup_users.update({user.email, other.email})
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await db_session.commit()
    await login_as(client, other)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME]

    response = await client.post(VERIFY, json={"token": raw})

    assert response.json()["detail"]["code"] == "auth.already_verified"
    assert client.cookies[settings.SESSION_COOKIE_NAME] == cookie
    me = await client.get(f"{API}/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == other.id
    assert await _session_count(db_session, user.id) == 0


async def test_verify_email_invalidates_the_other_verification_links(
    client, db_session, cleanup_users
):
    user = await create_user(db_session)
    cleanup_users.add(user.email)
    first, first_raw = await _verification_token(db_session, user.id)
    second, _ = await _verification_token(db_session, user.id)
    await db_session.commit()

    assert (await client.post(VERIFY, json={"token": first_raw})).status_code == 200

    stmt = (
        select(EmailToken)
        .where(EmailToken.id == second.id)
        .execution_options(populate_existing=True)
    )
    assert (await db_session.scalar(stmt)).used_at is not None


async def test_verify_email_revokes_the_session_of_another_account(
    client, db_session, outbox, cleanup_users
):
    """Verifying in a browser signed in as someone else signs that someone out (as login does)."""
    other = await create_verified_user(db_session)
    cleanup_users.add(other.email)
    await db_session.commit()
    await login_as(client, other)
    old_cookie = client.cookies[settings.SESSION_COOKIE_NAME]
    email, _ = await _register(client, cleanup_users)
    raw = _token_from(outbox[-1])

    response = await client.post(VERIFY, json={"token": raw})

    assert response.status_code == 200, response.text
    assert response.json()["email"] == email
    assert client.cookies[settings.SESSION_COOKIE_NAME] != old_cookie
    assert (await client.get(f"{API}/auth/me")).json()["email"] == email
    assert await _session_count(db_session, other.id, active_only=True) == 0
    client.cookies.set(settings.SESSION_COOKIE_NAME, old_cookie)
    assert (await client.get(f"{API}/auth/me")).status_code == 401


# --- resend verification ----------------------------------------------------------------------


RESENT = {
    "code": "auth.verification_resent",
    "message": "If an account exists for this address, a new verification email has been sent.",
}


async def test_resend_unknown_email(client, outbox):
    response = await client.post(RESEND, json={"email": unique_email("nobody")})

    assert response.status_code == 202
    assert response.json() == RESENT
    assert outbox == []


async def test_resend_for_unverified_user_issues_new_token(
    client, db_session, outbox, cleanup_users
):
    email, _ = await _register(client, cleanup_users)
    old_raw = _token_from(outbox[0])

    response = await client.post(RESEND, json={"email": email.upper()})

    assert response.status_code == 202
    assert response.json() == RESENT
    assert len(outbox) == 2
    assert outbox[1].to == email
    new_raw = _token_from(outbox[1])
    assert new_raw != old_raw

    user = await _user(db_session, email)
    assert "auth.verification_resent" in await _audit_actions(db_session, user.id)
    assert (
        await consume_email_token(db_session, raw_token=old_raw, purpose=TokenPurpose.VERIFY_EMAIL)
        is None
    )
    assert (
        await consume_email_token(db_session, raw_token=new_raw, purpose=TokenPurpose.VERIFY_EMAIL)
        is not None
    )
    await db_session.rollback()


async def test_resend_for_verified_user_sends_nothing(client, db_session, outbox, cleanup_users):
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    await db_session.commit()

    response = await client.post(RESEND, json={"email": user.email})

    assert response.status_code == 202
    assert response.json() == RESENT
    assert outbox == []


async def test_resend_for_disabled_user_sends_nothing(client, db_session, outbox, cleanup_users):
    user = await create_user(db_session, is_active=False)
    cleanup_users.add(user.email)
    await db_session.commit()

    response = await client.post(RESEND, json={"email": user.email})

    assert response.status_code == 202
    assert response.json() == RESENT
    assert outbox == []


async def test_resend_turnstile_failure(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "TURNSTILE_ENABLED", True)

    response = await client.post(RESEND, json={"email": unique_email()})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "auth.captcha_failed"


# Increment 7d: Turnstile on (as in production) for resend verification.


async def _committed_unverified(db, cleanup_users) -> User:
    user = await create_user(db)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def test_resend_turnstile_on_anonymous_without_token_is_rejected(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    user = await _committed_unverified(db_session, cleanup_users)

    response = await client.post(RESEND, json={"email": user.email})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "auth.captcha_failed"
    assert outbox == []
    assert not turnstile_on.calls.called


async def test_resend_turnstile_on_anonymous_with_valid_token_sends(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    user = await _committed_unverified(db_session, cleanup_users)

    response = await client.post(
        RESEND, json={"email": user.email, "turnstile_token": "good-token"}
    )

    assert response.status_code == 202, response.text
    assert response.json() == RESENT
    assert [m.to for m in outbox] == [user.email]
    assert TOKEN_RE.search(outbox[0].text)
    assert turnstile_on.calls.call_count == 1


async def test_resend_turnstile_on_anonymous_with_rejected_token(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    user = await _committed_unverified(db_session, cleanup_users)

    response = await client.post(RESEND, json={"email": user.email, "turnstile_token": "bad-token"})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "auth.captcha_failed"
    assert outbox == []


async def test_resend_turnstile_on_signed_in_same_unverified_user_needs_no_token(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    user = await _committed_unverified(db_session, cleanup_users)
    await login_as(client, user)

    # Different case: the address comparison is case-insensitive, like the CITEXT column.
    response = await client.post(RESEND, json={"email": user.email.upper()})

    assert response.status_code == 202, response.text
    assert response.json() == RESENT
    assert [m.to for m in outbox] == [user.email]
    assert not turnstile_on.calls.called


async def test_resend_turnstile_on_signed_in_other_address_needs_token(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    signed_in = await _committed_unverified(db_session, cleanup_users)
    other = await _committed_unverified(db_session, cleanup_users)
    await login_as(client, signed_in)

    response = await client.post(RESEND, json={"email": other.email})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "auth.captcha_failed"
    assert outbox == []


async def test_resend_turnstile_on_signed_in_verified_user_needs_token(
    client, db_session, outbox, cleanup_users, turnstile_on
):
    user = await create_verified_user(db_session)
    cleanup_users.add(user.email)
    await db_session.commit()
    await login_as(client, user)

    response = await client.post(RESEND, json={"email": user.email})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "auth.captcha_failed"


async def test_resend_invalid_email_is_validation_error(client):
    response = await client.post(RESEND, json={"email": "nope"})
    _assert_validation(response, "email")


# --- error format -----------------------------------------------------------------------------


async def test_validation_error_format(client):
    response = await client.post(REGISTER, json={"email": "x"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["fields"], dict)
    assert detail["fields"]["email"] == "value_error"
    assert detail["fields"]["password"] == "missing"
    assert detail["fields"]["accept_terms"] == "missing"


async def test_unknown_route_error_format(client):
    response = await client.get(f"{API}/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.404", "message": "Not Found"}}


async def test_method_not_allowed_keeps_allow_header(client):
    response = await client.get(REGISTER)

    assert response.status_code == 405
    assert response.json()["detail"]["code"] == "http.405"
    assert "POST" in response.headers["allow"]


async def test_http_exception_dict_detail_and_unhandled_error():
    import httpx
    from fastapi import HTTPException

    from app.main import create_app

    app = create_app()

    @app.get("/_boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/_coded")
    async def coded():
        raise HTTPException(status_code=418, detail={"code": "tea.pot", "message": "Short"})

    @app.get("/_empty")
    async def empty():
        raise HTTPException(status_code=204)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        boom_response = await ac.get("/_boom")
        coded_response = await ac.get("/_coded")
        empty_response = await ac.get("/_empty")

    assert boom_response.status_code == 500
    assert boom_response.json()["detail"]["code"] == "server.error"
    assert "kaboom" not in boom_response.text
    assert coded_response.status_code == 418
    assert coded_response.json() == {"detail": {"code": "tea.pot", "message": "Short"}}
    assert empty_response.status_code == 204
    assert empty_response.content == b""


# --- crud.user --------------------------------------------------------------------------------


async def test_crud_create_user_and_lookups(db_session):
    from app.crud.user import create_user as crud_create_user
    from app.crud.user import get_user_by_email, get_user_by_id, mark_verified

    uowm_id = await _uowm_id(db_session)
    email = unique_email("crud")
    user = await crud_create_user(
        db_session,
        email=email,
        password=STRONG_PASSWORD,
        display_name="Crud User",
        organisation_id=uowm_id,
        country="GR",
        locale="el",
    )

    assert user.role == "member"
    assert user.is_verified is False
    assert user.is_active is True
    assert user.created_at is not None
    assert user.organisation.short_name == "UOWM"
    assert user.notification_preferences.digest_frequency == "daily"

    assert (await get_user_by_email(db_session, email=email.upper())).id == user.id
    assert await get_user_by_email(db_session, email=unique_email("missing")) is None
    assert await get_user_by_id(db_session, user_id=-1) is None

    db_session.expunge_all()
    loaded = await get_user_by_id(db_session, user_id=user.id)
    assert "organisation" in loaded.__dict__
    assert "notification_preferences" in loaded.__dict__

    await mark_verified(db_session, user=loaded)
    assert (await get_user_by_id(db_session, user_id=user.id)).is_verified is True


async def test_crud_create_user_duplicate_keeps_transaction_usable(db_session):
    from app.core.exceptions import AppError
    from app.crud.user import create_user as crud_create_user

    email = unique_email("dup")
    await crud_create_user(db_session, email=email, password=STRONG_PASSWORD, display_name="One")

    with pytest.raises(AppError) as excinfo:
        await crud_create_user(
            db_session, email=email.upper(), password=STRONG_PASSWORD, display_name="Two"
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "auth.email_taken"
    # The savepoint was rolled back; the outer transaction still works.
    count = select(func.count()).select_from(User).where(User.email == email)
    assert await db_session.scalar(count) == 1


async def test_crud_create_user_policy_and_organisation_errors(db_session):
    from app.core.exceptions import AppError
    from app.core.security import PasswordPolicyError
    from app.crud.user import create_user as crud_create_user

    with pytest.raises(PasswordPolicyError) as policy:
        await crud_create_user(
            db_session, email=unique_email(), password="qwertyuiop", display_name="Weak"
        )
    assert policy.value.code == "auth.password_too_common"

    with pytest.raises(AppError) as org:
        await crud_create_user(
            db_session,
            email=unique_email(),
            password=STRONG_PASSWORD,
            display_name="Orgless",
            organisation_id=987_654,
        )
    assert org.value.status_code == 422
    assert org.value.fields == {"organisation_id": "not_found"}


# --- expertise at registration (increment 1o) -------------------------------------------------

ME = f"{API}/auth/me"


async def _seeded_tag_ids(db, *slugs: str) -> list[int]:
    from app.db.models import ExpertiseTag

    rows = (await db.execute(select(ExpertiseTag.slug, ExpertiseTag.id))).all()
    by_slug = {slug: tag_id for slug, tag_id in rows}
    return [by_slug[slug] for slug in slugs]


async def _verify_and_get_me(client, outbox) -> dict:
    assert (await client.post(VERIFY, json={"token": _token_from(outbox[0])})).status_code == 200
    response = await client.get(ME)
    assert response.status_code == 200, response.text
    return response.json()


async def _register_audit(db, user_id: int) -> AuditLog:
    return await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
            AuditLog.action == "auth.register",
        )
        .execution_options(populate_existing=True)
    )


async def test_register_with_expertise(client, db_session, outbox, cleanup_users):
    # Sent out of order; returned in sort_order.
    ids = await _seeded_tag_ids(db_session, "meteorology", "hydrology", "civil-protection")

    email, response = await _register(client, cleanup_users, expertise_ids=ids)

    assert response.status_code == 201, response.text
    assert set(response.json()) == {"id", "email", "display_name", "is_verified"}
    me = await _verify_and_get_me(client, outbox)
    assert [tag["slug"] for tag in me["expertise"]] == [
        "hydrology",
        "civil-protection",
        "meteorology",
    ]
    audit = await _register_audit(db_session, response.json()["id"])
    assert audit.metadata_ == {"locale": "en", "consent": True, "expertise_count": 3}


async def test_register_without_expertise(client, db_session, outbox, cleanup_users):
    _, response = await _register(client, cleanup_users)

    assert response.status_code == 201, response.text
    assert (await _verify_and_get_me(client, outbox))["expertise"] == []
    audit = await _register_audit(db_session, response.json()["id"])
    assert audit.metadata_["expertise_count"] == 0


async def test_register_too_many_expertise(client, db_session, outbox, cleanup_users):
    from app.db.models import ExpertiseTag

    ids = list((await db_session.scalars(select(ExpertiseTag.id).limit(9))).all())
    assert len(ids) == 9

    email, response = await _register(client, cleanup_users, expertise_ids=ids)

    _assert_validation(response, "expertise_ids")
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_unknown_expertise_creates_no_user(
    client, db_session, outbox, cleanup_users
):
    ids = await _seeded_tag_ids(db_session, "hydrology")

    email, response = await _register(client, cleanup_users, expertise_ids=[*ids, 987_654])

    _assert_validation(response, "expertise_ids", "not_found")
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_inactive_expertise_rejected(client, db_session, cleanup_users):
    from app.db.models import ExpertiseTag

    retired = ExpertiseTag(slug="zz-reg-inactive", label="Retired", sort_order=99, is_active=False)
    db_session.add(retired)
    await db_session.commit()
    try:
        email, response = await _register(client, cleanup_users, expertise_ids=[retired.id])

        _assert_validation(response, "expertise_ids", "not_found")
        assert await _user(db_session, email) is None
    finally:
        await db_session.delete(retired)
        await db_session.commit()


async def test_register_duplicate_expertise_ids_collapse(client, db_session, outbox, cleanup_users):
    hydrology = (await _seeded_tag_ids(db_session, "hydrology"))[0]

    _, response = await _register(client, cleanup_users, expertise_ids=[hydrology, hydrology])

    assert response.status_code == 201, response.text
    me = await _verify_and_get_me(client, outbox)
    assert [tag["id"] for tag in me["expertise"]] == [hydrology]
    audit = await _register_audit(db_session, response.json()["id"])
    assert audit.metadata_["expertise_count"] == 1


async def test_register_request_openapi_lists_expertise_ids(client):
    response = await client.get(f"{API}/openapi.json")

    assert response.status_code == 200
    schema = response.json()["components"]["schemas"]["RegisterRequest"]
    assert "expertise_ids" not in schema.get("required", [])
    field = schema["properties"]["expertise_ids"]
    assert field["type"] == "array"
    # Bounded like every id (7n): 1 to 2**31 - 1.
    assert field["items"] == {"type": "integer", "minimum": 1, "maximum": 2**31 - 1}
    assert field["maxItems"] == 8
    assert field.get("default") == []


async def test_crud_create_user_with_expertise(db_session):
    from app.core.exceptions import AppError
    from app.crud.user import create_user as crud_create_user

    ids = await _seeded_tag_ids(db_session, "meteorology", "hydrology")
    user = await crud_create_user(
        db_session,
        email=unique_email("crud-exp"),
        password=STRONG_PASSWORD,
        display_name="Expert",
        expertise_ids=[*ids, ids[0]],
    )
    assert [tag.slug for tag in user.expertise] == ["hydrology", "meteorology"]

    with pytest.raises(AppError) as excinfo:
        await crud_create_user(
            db_session,
            email=unique_email("crud-exp"),
            password=STRONG_PASSWORD,
            display_name="Unknown",
            expertise_ids=[987_654],
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.fields == {"expertise_ids": "not_found"}


# --- free-text "other" area of expertise (increment 7f) ---------------------------------------


async def test_register_with_expertise_other(client, db_session, outbox, cleanup_users):
    email, response = await _register(
        client, cleanup_users, expertise_other="  Coastal sediment transport  "
    )

    assert response.status_code == 201, response.text
    assert (await _user(db_session, email)).expertise_other == "Coastal sediment transport"
    me = await _verify_and_get_me(client, outbox)
    assert me["expertise_other"] == "Coastal sediment transport"


@pytest.mark.parametrize("value", ["", "   ", None])
async def test_register_blank_expertise_other_is_null(client, db_session, cleanup_users, value):
    email, response = await _register(client, cleanup_users, expertise_other=value)

    assert response.status_code == 201, response.text
    assert (await _user(db_session, email)).expertise_other is None


async def test_register_without_expertise_other(client, db_session, outbox, cleanup_users):
    _, response = await _register(client, cleanup_users)

    assert response.status_code == 201, response.text
    assert (await _verify_and_get_me(client, outbox))["expertise_other"] is None


async def test_register_expertise_other_too_long(client, db_session, outbox, cleanup_users):
    email, response = await _register(client, cleanup_users, expertise_other="e" * 201)

    _assert_validation(response, "expertise_other")
    assert await _user(db_session, email) is None
    assert outbox == []


async def test_register_expertise_other_at_limit(client, db_session, cleanup_users):
    email, response = await _register(client, cleanup_users, expertise_other="e" * 200)

    assert response.status_code == 201, response.text
    assert (await _user(db_session, email)).expertise_other == "e" * 200
