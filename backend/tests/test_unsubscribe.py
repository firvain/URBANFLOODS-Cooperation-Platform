"""One-click unsubscribe (RFC 8058) for the notification emails.

``services/unsubscribe.py`` signs a stateless token (``v1.<user_id>.<preference>.<signature>``,
HMAC-SHA256 with ``SECRET_KEY``). ``POST /api/v1/notifications/unsubscribe?token=…`` turns that
one preference off. Mail clients POST it without a session and without ``X-Requested-With``, so
the route is exempt from the CSRF middleware; it acts on the signed token only, never on a
session. GET does not exist (link scanners would unsubscribe people).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.core import csrf
from app.core.config import settings
from app.crud import user as crud_user
from app.db.models import AuditLog, NotificationPreference
from app.services import unsubscribe
from app.services.unsubscribe import (
    PREFERENCES,
    make_token,
    read_token,
    unsubscribe_url,
)
from tests.factories import create_verified_user, login_as

API = settings.API_V1_PREFIX
PATH = f"{API}/notifications/unsubscribe"
ONE_CLICK = {"List-Unsubscribe": "One-Click"}
ALL_PREFERENCES = (
    "reply_to_my_thread",
    "comment_on_my_post",
    "reply_to_my_reply",
    "moderation_decisions",
    "admin_digest",
)


# --- token ------------------------------------------------------------------------------------


def test_preferences_are_the_switchable_email_kinds() -> None:
    assert PREFERENCES == frozenset(ALL_PREFERENCES)


@pytest.mark.parametrize("preference", ALL_PREFERENCES)
def test_token_round_trips(preference) -> None:
    token = make_token(42, preference)
    assert token.startswith("v1.42.")
    assert read_token(token) == (42, preference)


def test_token_is_url_safe_and_carries_no_secret() -> None:
    token = make_token(7, "admin_digest")
    assert all(c.isalnum() or c in "._-" for c in token)
    assert settings.SECRET_KEY not in token


def test_unknown_preference_cannot_be_signed() -> None:
    with pytest.raises(ValueError):
        make_token(7, "digest_frequency")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("v1.", "v2.", 1),
        lambda t: t.replace(".7.", ".8.", 1),
        lambda t: t.replace("admin_digest", "reply_to_my_thread"),
        lambda t: t[:-1] + ("A" if t[-1] != "A" else "B"),
        lambda t: t + ".extra",
        lambda t: t.rsplit(".", 1)[0],
        lambda t: "",
        lambda t: "garbage",
        lambda t: "v1.-7.admin_digest.sig",
        lambda t: "v1.abc.admin_digest.sig",
    ],
)
def test_tampered_token_is_rejected(mutate) -> None:
    assert read_token(mutate(make_token(7, "admin_digest"))) is None


def test_validly_signed_token_with_an_unknown_preference_is_rejected() -> None:
    signature = unsubscribe._sign("v1", 7, "digest_frequency")
    assert read_token(f"v1.7.digest_frequency.{signature}") is None


def test_token_depends_on_the_secret_key(monkeypatch) -> None:
    token = make_token(7, "admin_digest")
    monkeypatch.setattr(settings, "SECRET_KEY", "another-secret-key-of-enough-length-0123456789")
    assert make_token(7, "admin_digest") != token
    assert read_token(token) is None


def test_unsubscribe_url_points_at_the_api_through_the_frontend() -> None:
    url = unsubscribe_url(7, "comment_on_my_post")
    frontend = settings.FRONTEND_URL.rstrip("/")
    assert url.startswith(f"{frontend}{PATH}?token=")
    token = parse_qs(urlsplit(url).query)["token"][0]
    assert read_token(token) == (7, "comment_on_my_post")


def test_route_is_exempt_from_csrf_and_nothing_else_is() -> None:
    assert csrf._is_exempt(PATH)
    assert not csrf._is_exempt(f"{API}/notifications/other")
    assert not csrf._is_exempt(f"{API}/auth/me/notifications")


# --- endpoint ---------------------------------------------------------------------------------


@pytest.fixture
async def bare(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the running app without ``X-Requested-With`` and without a session: a mail
    client or a mail provider's server."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def member(db_session, cleanup_users):
    """A member who switched the member notifications on (off by default since 2026-10-31), so
    every preference starts on and an unsubscribe has something to switch off."""
    user = await create_verified_user(db_session, notify=True)
    cleanup_users.add(user.email)
    await db_session.commit()
    return user


async def _preferences(db_session, user_id: int) -> NotificationPreference | None:
    """The row as committed by the app (``populate_existing`` refreshes a cached instance)."""
    stmt = (
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    return await db_session.scalar(stmt)


async def _audit(db_session, user_id: int) -> list[AuditLog]:
    rows = await db_session.scalars(
        select(AuditLog).where(
            AuditLog.action == "notifications.unsubscribed", AuditLog.actor_id == user_id
        )
    )
    return list(rows)


@pytest.mark.parametrize("preference", ALL_PREFERENCES)
async def test_valid_token_turns_off_only_that_preference_and_audits(
    bare, db_session, member, preference
) -> None:
    response = await bare.post(
        PATH, params={"token": make_token(member.id, preference)}, data=ONE_CLICK
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "unsubscribed"}
    preferences = await _preferences(db_session, member.id)
    for name in ALL_PREFERENCES:
        assert getattr(preferences, name) is (name != preference), name
    rows = await _audit(db_session, member.id)
    assert len(rows) == 1
    assert rows[0].target_type == "user"
    assert rows[0].target_id == member.id
    assert rows[0].metadata_ == {"preference": preference, "via": "list-unsubscribe"}


async def test_repeated_unsubscribe_is_idempotent_and_audited_once(bare, db_session, member):
    token = make_token(member.id, "reply_to_my_thread")
    for _ in range(3):
        response = await bare.post(PATH, params={"token": token}, data=ONE_CLICK)
        assert response.status_code == 200
        assert response.json() == {"status": "unsubscribed"}
    assert len(await _audit(db_session, member.id)) == 1


async def test_missing_preferences_row_is_created_with_that_switch_off(
    bare, db_session, member
) -> None:
    row = await db_session.get(NotificationPreference, member.id)
    await db_session.delete(row)
    await db_session.commit()

    response = await bare.post(
        PATH, params={"token": make_token(member.id, "moderation_decisions")}, data=ONE_CLICK
    )

    assert response.status_code == 200
    preferences = await _preferences(db_session, member.id)
    assert preferences is not None
    assert preferences.moderation_decisions is False
    # The other switches have the defaults of a new row.
    assert preferences.reply_to_my_thread is False
    assert preferences.admin_digest is True


async def test_works_without_body_too(bare, db_session, member) -> None:
    response = await bare.post(PATH, params={"token": make_token(member.id, "admin_digest")})
    assert response.status_code == 200
    assert (await _preferences(db_session, member.id)).admin_digest is False


async def test_tampered_token_is_400_and_changes_nothing(bare, db_session, member) -> None:
    token = make_token(member.id, "reply_to_my_thread")
    response = await bare.post(PATH, params={"token": token[:-2] + "xx"}, data=ONE_CLICK)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "notifications.invalid_token"
    assert (await _preferences(db_session, member.id)).reply_to_my_thread is True
    assert await _audit(db_session, member.id) == []


async def test_signed_token_with_a_wrong_preference_is_400(bare, db_session, member) -> None:
    signature = unsubscribe._sign("v1", member.id, "digest_frequency")
    response = await bare.post(
        PATH, params={"token": f"v1.{member.id}.digest_frequency.{signature}"}, data=ONE_CLICK
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "notifications.invalid_token"


@pytest.mark.parametrize("params", [{}, {"token": ""}, {"token": "x" * 1000}])
async def test_missing_or_oversized_token_is_400(bare, params) -> None:
    response = await bare.post(PATH, params=params, data=ONE_CLICK)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "notifications.invalid_token"


async def test_unknown_user_is_a_silent_no_op(bare, db_session) -> None:
    response = await bare.post(
        PATH, params={"token": make_token(2_000_000_000, "admin_digest")}, data=ONE_CLICK
    )
    assert response.status_code == 200
    assert response.json() == {"status": "unsubscribed"}
    assert await _preferences(db_session, 2_000_000_000) is None


async def test_deleted_user_is_a_silent_no_op(bare, db_session, cleanup_user_ids) -> None:
    user = await create_verified_user(db_session)
    cleanup_user_ids.add(user.id)
    await crud_user.anonymise_user(db_session, user=user)
    await db_session.commit()

    response = await bare.post(
        PATH, params={"token": make_token(user.id, "reply_to_my_thread")}, data=ONE_CLICK
    )

    assert response.status_code == 200
    assert response.json() == {"status": "unsubscribed"}
    # Not recreated for an anonymised account, and nothing audited.
    assert await _preferences(db_session, user.id) is None
    assert await _audit(db_session, user.id) == []


async def test_get_is_not_allowed(bare, db_session, member) -> None:
    """GET must not change state: link scanners would unsubscribe people."""
    response = await bare.get(PATH, params={"token": make_token(member.id, "admin_digest")})
    assert response.status_code == 405
    assert (await _preferences(db_session, member.id)).admin_digest is True


async def test_session_cookie_without_header_and_foreign_origin_pass(
    client, bare, db_session, member, cleanup_users
) -> None:
    """A webmail page or client may POST cross-origin, even from a browser that holds a
    session; the CSRF middleware must not block it, and the session is ignored: the token
    alone decides whose preference changes."""
    other = await create_verified_user(db_session, notify=True)
    cleanup_users.add(other.email)
    await db_session.commit()
    await login_as(client, other)
    bare.cookies.set(settings.SESSION_COOKIE_NAME, client.cookies[settings.SESSION_COOKIE_NAME])

    response = await bare.post(
        PATH,
        params={"token": make_token(member.id, "comment_on_my_post")},
        data=ONE_CLICK,
        headers={"Origin": "https://mail.example.com"},
    )

    assert response.status_code == 200, response.text
    assert (await _preferences(db_session, member.id)).comment_on_my_post is False
    assert (await _preferences(db_session, other.id)).comment_on_my_post is True


async def test_other_unsafe_routes_still_need_the_header(client, bare, db_session, member):
    await login_as(client, member)
    bare.cookies.set(settings.SESSION_COOKIE_NAME, client.cookies[settings.SESSION_COOKIE_NAME])
    response = await bare.post(f"{API}/auth/logout")
    assert response.status_code == 403
