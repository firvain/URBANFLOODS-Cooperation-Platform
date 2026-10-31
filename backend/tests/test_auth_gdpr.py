"""Increment 1i: GDPR self-service (data export, anonymising account deletion) and notification
preferences.

The ``client`` runs the app with its own sessions and commits through ``get_db_tx``, so rows it
writes are visible to ``db_session``. Users created here are registered with ``cleanup_users``
(by email) and ``cleanup_user_ids`` (by id, for accounts that end up anonymised as
``deleted-<id>@invalid``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.crud import audit as crud_audit
from app.crud import user as crud_user
from app.crud.session import create_session, revoke_session
from app.crud.token import create_email_token
from app.db.enums import TokenPurpose, UserRole
from app.db.models import (
    Attachment,
    AuditLog,
    EmailToken,
    NotificationPreference,
    Organisation,
    Session,
    User,
)
from tests.factories import (
    DEFAULT_PASSWORD,
    create_admin,
    create_superadmin,
    create_user,
    create_verified_user,
    login_as,
    unique_email,
)

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
REGISTER = f"{API}/auth/register"
ME = f"{API}/auth/me"
EXPORT = f"{API}/auth/me/export"
NOTIFICATIONS = f"{API}/auth/me/notifications"
COOKIE = settings.SESSION_COOKIE_NAME
NOT_AUTHENTICATED = "auth.not_authenticated"
FILENAME_RE = re.compile(r'^attachment; filename="urbanfloods-account-(\d+)-(\d{8})\.json"$')
FORBIDDEN_KEYS = {"password_hash", "token_hash", "password", "token"}
DEFAULT_PREFERENCES = {
    "reply_to_my_thread": True,
    "comment_on_my_post": True,
    "reply_to_my_reply": True,
    "admin_digest": True,
    "moderation_decisions": True,
    "digest_frequency": "daily",
}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
async def avatar_attachment_id(database_url: str) -> AsyncIterator[int]:
    """A committed attachment (no uploader) to use as an avatar; deleted afterwards."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session, session.begin():
        attachment = Attachment(
            storage_path=f"test/{uuid.uuid4().hex}.webp",
            original_filename="avatar.png",
            mime="image/webp",
            size_bytes=1,
            width=1,
            height=1,
            alt_text="Avatar",
        )
        session.add(attachment)
        await session.flush()
        attachment_id = attachment.id
    yield attachment_id
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Attachment).where(Attachment.id == attachment_id))


async def _committed(
    db, cleanup_users, cleanup_user_ids, factory=create_verified_user, **kwargs
) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    cleanup_user_ids.add(user.id)
    await db.commit()
    return user


async def _signed_in(
    client, db, cleanup_users, cleanup_user_ids, factory=create_verified_user, **kwargs
) -> User:
    user = await _committed(db, cleanup_users, cleanup_user_ids, factory=factory, **kwargs)
    await login_as(client, user)
    return user


async def _reload_user(db, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _audit(db, user_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _uowm(db) -> Organisation:
    return (
        await db.execute(select(Organisation).where(Organisation.short_name == "UOWM"))
    ).scalar_one()


def _delete_me(client, password: str = DEFAULT_PASSWORD):
    return client.request("DELETE", ME, json={"current_password": password})


async def _login(client, email: str, password: str = DEFAULT_PASSWORD):
    return await client.post(LOGIN, json={"email": email, "password": password})


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_validation(response, field: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail


def _assert_cookie_cleared(response) -> None:
    cookie = response.headers.get("set-cookie", "")
    assert cookie.startswith(f"{COOKIE}="), cookie
    lowered = cookie.lower()
    assert "max-age=0" in lowered or "expires=thu, 01 jan 1970" in lowered, cookie


def _all_keys(value: Any) -> set[str]:
    """Every dict key at any depth of a decoded JSON document."""
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys |= _all_keys(item)
        return keys
    return set()


# --- export -----------------------------------------------------------------------------------


async def test_export_requires_auth(client):
    _assert_error(await client.get(EXPORT), 401, NOT_AUTHENTICATED)


async def test_export_contents(client, db_session, cleanup_users, cleanup_user_ids):
    uowm = await _uowm(db_session)
    user = await _committed(
        db_session,
        cleanup_users,
        cleanup_user_ids,
        organisation_id=uowm.id,
        country="GR",
        bio="Hydrologist.",
        display_name="Export Person",
    )
    other = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await crud_audit.log_action(
        db_session,
        actor_id=user.id,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        metadata={"locale": "en", "consent": True},
    )
    # By someone else, about this user: included. By someone else about someone else: not.
    await crud_audit.log_action(
        db_session, actor_id=other.id, action="admin.trust", target_type="user", target_id=user.id
    )
    await crud_audit.log_action(
        db_session, actor_id=other.id, action="auth.logout", target_type="user", target_id=other.id
    )
    await create_email_token(db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD)
    await db_session.commit()
    await login_as(client, user, user_agent="Exporter/1.0")

    response = await client.get(EXPORT)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    match = FILENAME_RE.match(response.headers["content-disposition"])
    assert match, response.headers["content-disposition"]
    assert int(match.group(1)) == user.id
    assert match.group(2) == datetime.now(UTC).strftime("%Y%m%d")

    body = response.json()
    assert set(body) == {
        "exported_at",
        "format_version",
        "licence_note",
        "user",
        "notification_preferences",
        "sessions",
        "audit_log",
        "content",
        "attachments",
        "reports_made",
    }
    assert body["format_version"] == 2
    assert body["licence_note"] == settings.CONTENT_LICENSE_URL
    exported_at = datetime.fromisoformat(body["exported_at"])
    assert abs((datetime.now(UTC) - exported_at).total_seconds()) < 60

    exported_user = body["user"]
    assert set(exported_user) == {
        "id",
        "email",
        "display_name",
        "organisation",
        "organisation_other",
        "country",
        "locale",
        "bio",
        "role",
        "is_verified",
        "trusted_at",
        "created_at",
        "updated_at",
        "last_login_at",
        "expertise",
        "show_email",
        "show_in_directory",
    }
    assert exported_user["id"] == user.id
    assert exported_user["email"] == user.email
    assert exported_user["display_name"] == "Export Person"
    assert exported_user["organisation"] == {
        "id": uowm.id,
        "name": uowm.name,
        "short_name": "UOWM",
    }
    assert exported_user["organisation_other"] is None
    assert exported_user["country"] == "GR"
    assert exported_user["locale"] == "en"
    assert exported_user["bio"] == "Hydrologist."
    assert exported_user["role"] == "member"
    assert exported_user["is_verified"] is True
    assert exported_user["trusted_at"] is None
    assert exported_user["last_login_at"] is not None

    assert body["notification_preferences"] == DEFAULT_PREFERENCES

    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert set(session) == {
        "id",
        "created_at",
        "last_seen_at",
        "expires_at",
        "user_agent",
        "revoked_at",
    }
    assert session["user_agent"] == "Exporter/1.0"
    assert session["revoked_at"] is None

    for row in body["audit_log"]:
        assert set(row) == {"action", "target_type", "target_id", "metadata", "created_at"}
    actions = [row["action"] for row in body["audit_log"]]
    assert "auth.register" in actions
    assert "auth.login" in actions
    assert "admin.trust" in actions
    assert "auth.logout" not in actions  # the other user's own row
    assert "auth.data_exported" not in actions  # written after the export is built
    register_row = next(row for row in body["audit_log"] if row["action"] == "auth.register")
    assert register_row["metadata"] == {"locale": "en", "consent": True}
    assert register_row["target_type"] == "user"
    assert register_row["target_id"] == user.id

    assert body["content"] == {"posts": [], "threads": [], "replies": [], "comments": []}
    assert body["attachments"] == []
    assert body["reports_made"] == []

    assert _all_keys(body).isdisjoint(FORBIDDEN_KEYS), _all_keys(body) & FORBIDDEN_KEYS
    stored = await _reload_user(db_session, user.id)
    assert stored.password_hash not in response.text

    rows = await _audit(db_session, user.id, "auth.data_exported")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id


async def test_export_includes_revoked_sessions_and_no_organisation(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(
        db_session, cleanup_users, cleanup_user_ids, organisation_other="Some NGO"
    )
    old, _ = await create_session(db_session, user_id=user.id, user_agent="Old/1.0")
    await revoke_session(db_session, session_id=old.id)
    await db_session.commit()
    await login_as(client, user)

    body = (await client.get(EXPORT)).json()

    assert body["user"]["organisation"] is None
    assert body["user"]["organisation_other"] == "Some NGO"
    assert len(body["sessions"]) == 2
    revoked = next(item for item in body["sessions"] if item["id"] == str(old.id))
    assert revoked["revoked_at"] is not None


async def test_export_unverified_user_allowed(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _signed_in(
        client, db_session, cleanup_users, cleanup_user_ids, factory=create_user
    )

    response = await client.get(EXPORT)

    assert response.status_code == 200, response.text
    assert response.json()["user"]["is_verified"] is False
    assert response.json()["user"]["id"] == user.id


# --- delete account ---------------------------------------------------------------------------


async def test_delete_requires_auth(client):
    _assert_error(await _delete_me(client), 401, NOT_AUTHENTICATED)


async def test_delete_wrong_password(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)

    response = await _delete_me(client, "not-my-password-at-all")

    _assert_error(response, 400, "auth.invalid_credentials")
    assert len(await _audit(db_session, user.id, "auth.delete_failed")) == 1
    assert await _audit(db_session, user.id, "auth.account_deleted") == []
    stored = await _reload_user(db_session, user.id)
    assert stored.email == user.email
    assert stored.is_active is True
    assert stored.deleted_at is None
    assert (await client.get(ME)).status_code == 200


async def test_delete_missing_password(client, db_session, cleanup_users, cleanup_user_ids):
    await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)

    _assert_validation(await client.request("DELETE", ME, json={}), "current_password")


async def test_delete_account_anonymises(
    client, other_client, db_session, outbox, cleanup_users, cleanup_user_ids, avatar_attachment_id
):
    uowm = await _uowm(db_session)
    user = await _committed(
        db_session,
        cleanup_users,
        cleanup_user_ids,
        organisation_id=uowm.id,
        country="GR",
        bio="Hydrologist.",
        avatar_attachment_id=avatar_attachment_id,
        trusted_at=datetime.now(UTC),
        display_name="Soon Gone",
    )
    old_email = user.email
    await create_email_token(db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD)
    await create_email_token(
        db_session,
        user_id=user.id,
        purpose=TokenPurpose.CHANGE_EMAIL,
        new_email=unique_email("new"),
    )
    await db_session.commit()
    await login_as(client, user)
    await login_as(other_client, user)

    response = await _delete_me(client)

    assert response.status_code == 204, response.text
    assert response.content == b""
    _assert_cookie_cleared(response)
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)
    _assert_error(await other_client.get(ME), 401, NOT_AUTHENTICATED)

    stored = await _reload_user(db_session, user.id)
    assert stored.email == f"deleted-{user.id}@invalid"
    assert stored.display_name == "Deleted user"
    assert stored.password_hash == ""
    assert stored.organisation_id is None
    assert stored.organisation_other is None
    assert stored.country is None
    assert stored.bio is None
    assert stored.avatar_attachment_id is None
    assert stored.is_active is False
    assert stored.is_verified is False
    assert stored.role == UserRole.MEMBER
    assert stored.trusted_at is None
    assert stored.deleted_at is not None

    sessions = (
        await db_session.scalars(
            select(Session)
            .where(Session.user_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert len(sessions) == 2
    assert all(session.revoked_at is not None for session in sessions)

    tokens = (
        await db_session.scalars(
            select(EmailToken)
            .where(EmailToken.user_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert len(tokens) == 2
    assert all(token.used_at is not None for token in tokens)

    assert await db_session.get(NotificationPreference, user.id) is None

    rows = await _audit(db_session, user.id, "auth.account_deleted")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id

    _assert_error(await _login(other_client, old_email), 401, "auth.invalid_credentials")

    again = await client.post(
        REGISTER,
        json={
            "email": old_email,
            "password": "flood-plain-river-delta-42",
            "display_name": "Back Again",
            "accept_terms": True,
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != user.id


async def test_delete_clears_free_text_organisation_and_role(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _signed_in(
        client,
        db_session,
        cleanup_users,
        cleanup_user_ids,
        factory=create_admin,
        organisation_other="Some NGO",
    )

    assert (await _delete_me(client)).status_code == 204

    stored = await _reload_user(db_session, user.id)
    assert stored.organisation_other is None
    assert stored.role == UserRole.MEMBER


async def test_delete_unverified_user(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _signed_in(
        client, db_session, cleanup_users, cleanup_user_ids, factory=create_user
    )

    assert (await _delete_me(client)).status_code == 204
    assert (await _reload_user(db_session, user.id)).deleted_at is not None


async def test_delete_last_superadmin_conflict(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _signed_in(
        client, db_session, cleanup_users, cleanup_user_ids, factory=create_superadmin
    )
    assert await crud_user.count_superadmins(db_session) == 1, "test needs a sole superadmin"

    response = await _delete_me(client)

    _assert_error(response, 409, "admin.last_superadmin")
    stored = await _reload_user(db_session, user.id)
    assert stored.email == user.email
    assert stored.role == UserRole.SUPERADMIN
    assert stored.is_active is True
    assert stored.deleted_at is None
    assert stored.password_hash != ""
    assert await db_session.get(NotificationPreference, user.id) is not None
    assert await _audit(db_session, user.id, "auth.account_deleted") == []
    assert (await client.get(ME)).status_code == 200


async def test_delete_superadmin_when_another_exists(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _signed_in(
        client, db_session, cleanup_users, cleanup_user_ids, factory=create_superadmin
    )
    await _committed(db_session, cleanup_users, cleanup_user_ids, factory=create_superadmin)

    assert (await _delete_me(client)).status_code == 204
    stored = await _reload_user(db_session, user.id)
    assert stored.role == UserRole.MEMBER
    assert stored.deleted_at is not None


# --- notification preferences -----------------------------------------------------------------


async def test_notifications_require_auth(client):
    _assert_error(await client.get(NOTIFICATIONS), 401, NOT_AUTHENTICATED)
    _assert_error(await client.put(NOTIFICATIONS, json=DEFAULT_PREFERENCES), 401, NOT_AUTHENTICATED)


async def test_notifications_defaults(client, db_session, cleanup_users, cleanup_user_ids):
    await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)

    response = await client.get(NOTIFICATIONS)

    assert response.status_code == 200, response.text
    assert response.json() == DEFAULT_PREFERENCES


async def test_notifications_update(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)
    wanted = {**DEFAULT_PREFERENCES, "admin_digest": False, "digest_frequency": "weekly"}

    response = await client.put(NOTIFICATIONS, json=wanted)

    assert response.status_code == 200, response.text
    assert response.json() == wanted
    assert (await client.get(NOTIFICATIONS)).json() == wanted
    stored = await db_session.get(NotificationPreference, user.id, populate_existing=True)
    assert stored is not None
    assert stored.admin_digest is False
    assert stored.digest_frequency == "weekly"
    rows = await _audit(db_session, user.id, "auth.notifications_updated")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"fields": ["admin_digest", "digest_frequency"]}


async def test_notifications_update_unchanged_writes_no_audit(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)

    response = await client.put(NOTIFICATIONS, json=DEFAULT_PREFERENCES)

    assert response.status_code == 200, response.text
    assert response.json() == DEFAULT_PREFERENCES
    assert await _audit(db_session, user.id, "auth.notifications_updated") == []


async def test_notifications_update_missing_field(
    client, db_session, cleanup_users, cleanup_user_ids
):
    await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)
    body = dict(DEFAULT_PREFERENCES)
    del body["reply_to_my_reply"]

    _assert_validation(await client.put(NOTIFICATIONS, json=body), "reply_to_my_reply")


async def test_notifications_update_invalid_frequency(
    client, db_session, cleanup_users, cleanup_user_ids
):
    await _signed_in(client, db_session, cleanup_users, cleanup_user_ids)
    body = {**DEFAULT_PREFERENCES, "digest_frequency": "hourly"}

    _assert_validation(await client.put(NOTIFICATIONS, json=body), "digest_frequency")
