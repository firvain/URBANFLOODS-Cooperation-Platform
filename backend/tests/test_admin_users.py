"""Increment 1h: admin user management (list, detail, PATCH, promote/demote/ban/unban/trust/
untrust/resend-verification) and its authorisation rules.

Every user is committed (the app uses its own sessions) and registered with ``cleanup_users``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.crud import user as crud_user
from app.db.enums import UserRole
from app.db.models import AuditLog, EmailToken, Organisation, Session, User
from tests.factories import (
    DEFAULT_PASSWORD,
    create_admin,
    create_superadmin,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
USERS = f"{API}/admin/users/"
ME = f"{API}/auth/me"
LOGIN = f"{API}/auth/login"
VERIFY = f"{API}/auth/verify-email"
TOKEN_RE = re.compile(r"/verify-email\?token=([A-Za-z0-9_\-]+)")

ACTIONS = ("promote", "demote", "ban", "unban", "trust", "untrust", "resend-verification")


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _signed_in(client, db, cleanup_users, factory=create_admin, **kwargs) -> User:
    user = await _committed(db, cleanup_users, factory=factory, **kwargs)
    await login_as(client, user)
    return user


async def _reload(db, user_id: int) -> User:
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
    )
    return list((await db.scalars(stmt)).all())


async def _active_sessions(db, user_id: int) -> int:
    stmt = select(func.count()).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    return await db.scalar(stmt)


def _url(user_id: int, action: str | None = None) -> str:
    return f"{USERS}{user_id}" + (f"/{action}" if action else "")


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _tag() -> str:
    """A token to put in display names so a ``q`` filter isolates this test's users."""
    return f"zq{uuid.uuid4().hex[:10]}"


# --- authorisation ----------------------------------------------------------------------------


async def test_list_requires_login(client):
    _assert_error(await client.get(USERS), 401, "auth.not_authenticated")


async def test_list_forbidden_for_member(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users, factory=create_verified_user)
    _assert_error(await client.get(USERS), 403, "auth.forbidden")


async def test_list_by_admin(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)

    response = await client.get(USERS, params={"q": admin.email})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == admin.id
    assert item["email"] == admin.email
    assert item["role"] == "admin"
    assert item["is_active"] is True
    assert item["last_login_at"] is not None
    assert item["deleted_at"] is None
    assert item["organisation_other"] is None
    assert item["is_trusted"] is False
    assert "password_hash" not in item


@pytest.mark.parametrize("action", ACTIONS)
async def test_actions_require_admin(client, db_session, cleanup_users, action):
    target = await _committed(db_session, cleanup_users)

    _assert_error(await client.post(_url(target.id, action)), 401, "auth.not_authenticated")
    _assert_error(await client.get(_url(target.id)), 401, "auth.not_authenticated")
    _assert_error(await client.patch(_url(target.id), json={}), 401, "auth.not_authenticated")

    await _signed_in(client, db_session, cleanup_users, factory=create_verified_user)
    _assert_error(await client.post(_url(target.id, action)), 403, "auth.forbidden")
    _assert_error(await client.get(_url(target.id)), 403, "auth.forbidden")
    _assert_error(await client.patch(_url(target.id), json={}), 403, "auth.forbidden")
    assert (await _reload(db_session, target.id)).role == UserRole.MEMBER


@pytest.mark.parametrize("action", ACTIONS)
async def test_actions_unknown_user(client, db_session, cleanup_users, action):
    await _signed_in(client, db_session, cleanup_users)
    _assert_error(await client.post(_url(999999, action)), 404, "users.not_found")


async def test_actions_on_deleted_user(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await create_verified_user(db_session, deleted_at=datetime.now(UTC))
    cleanup_users.add(target.email)
    await db_session.commit()

    _assert_error(await client.post(_url(target.id, "promote")), 409, "admin.user_deleted")
    # Still visible to admins.
    response = await client.get(_url(target.id))
    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None


# --- list filters and detail ------------------------------------------------------------------


async def test_list_filters(client, db_session, cleanup_users):
    tag = _tag()
    uowm_id = await db_session.scalar(
        select(Organisation.id).where(Organisation.short_name == "UOWM")
    )
    admin = await _signed_in(client, db_session, cleanup_users, display_name=f"{tag} admin")
    member = await _committed(
        db_session, cleanup_users, display_name=f"{tag} member", organisation_id=uowm_id
    )
    trusted = await _committed(
        db_session, cleanup_users, display_name=f"{tag} trusted", trusted_at=datetime.now(UTC)
    )
    unverified = await _committed(
        db_session, cleanup_users, factory=create_user, display_name=f"{tag} unverified"
    )
    banned = await _committed(
        db_session, cleanup_users, display_name=f"{tag} banned", is_active=False
    )

    async def ids(**params) -> list[int]:
        response = await client.get(USERS, params={"q": tag, **params})
        assert response.status_code == 200, response.text
        body = response.json()
        if "limit" not in params:
            assert body["total"] == len(body["items"])
        return [item["id"] for item in body["items"]]

    # Newest first.
    assert await ids() == [banned.id, unverified.id, trusted.id, member.id, admin.id]
    assert await ids(role="admin") == [admin.id]
    assert set(await ids(role="member")) == {banned.id, unverified.id, trusted.id, member.id}
    assert await ids(trusted="true") == [trusted.id]
    assert trusted.id not in await ids(trusted="false")
    assert await ids(verified="false") == [unverified.id]
    assert await ids(active="false") == [banned.id]
    assert await ids(organisation_id=uowm_id) == [member.id]
    assert await ids(q=tag.upper()) == await ids()
    assert await ids(q=member.email) == [member.id]
    assert await ids(skip=1, limit=2) == [unverified.id, trusted.id]

    response = await client.get(USERS, params={"q": tag, "limit": 1})
    assert response.json()["total"] == 5


@pytest.mark.parametrize(
    "params",
    [{"limit": 201}, {"limit": 0}, {"skip": -1}, {"role": "owner"}, {"q": "x" * 201}],
)
async def test_list_query_validation(client, db_session, cleanup_users, params):
    await _signed_in(client, db_session, cleanup_users)
    response = await client.get(USERS, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "validation.failed"


async def test_get_user(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, organisation_other="Some NGO")

    response = await client.get(_url(target.id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == target.id
    assert body["organisation_other"] == "Some NGO"
    assert body["last_login_at"] is None


async def test_get_user_not_found(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    _assert_error(await client.get(_url(999999)), 404, "users.not_found")


# --- promote / demote -------------------------------------------------------------------------


async def test_promote_member_to_admin(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.post(_url(target.id, "promote"))

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    assert (await _reload(db_session, target.id)).role == UserRole.ADMIN
    rows = await _audit(db_session, target.id, "admin.promote")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"from": "member", "to": "admin"}


async def test_promote_already_admin_is_conflict(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_admin)

    response = await client.post(_url(target.id, "promote"))

    _assert_error(response, 409, "admin.invalid_role_change")
    assert await _audit(db_session, target.id, "admin.promote") == []


async def test_promote_to_superadmin_needs_superadmin(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.post(_url(target.id, "promote"), params={"to": "superadmin"})

    _assert_error(response, 403, "auth.forbidden")
    assert (await _reload(db_session, target.id)).role == UserRole.MEMBER


async def test_promote_to_superadmin_by_superadmin(client, db_session, cleanup_users):
    superadmin = await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    target = await _committed(db_session, cleanup_users, factory=create_admin)

    response = await client.post(_url(target.id, "promote"), params={"to": "superadmin"})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "superadmin"
    rows = await _audit(db_session, target.id, "admin.promote")
    assert rows[0].actor_id == superadmin.id
    assert rows[0].metadata_ == {"from": "admin", "to": "superadmin"}


async def test_promote_invalid_target_role(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    target = await _committed(db_session, cleanup_users)
    response = await client.post(_url(target.id, "promote"), params={"to": "member"})
    assert response.status_code == 422, response.text


async def test_demote_admin_to_member(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_admin)

    response = await client.post(_url(target.id, "demote"))

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "member"
    rows = await _audit(db_session, target.id, "admin.demote")
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"from": "admin", "to": "member"}


async def test_demote_member_is_conflict(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)
    _assert_error(await client.post(_url(target.id, "demote")), 409, "admin.invalid_role_change")


async def test_demote_superadmin_by_admin_forbidden(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_superadmin)

    _assert_error(await client.post(_url(target.id, "demote")), 403, "auth.forbidden")
    assert (await _reload(db_session, target.id)).role == UserRole.SUPERADMIN


async def test_demote_superadmin_by_superadmin(client, db_session, cleanup_users):
    actor = await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    target = await _committed(db_session, cleanup_users, factory=create_superadmin)

    response = await client.post(_url(target.id, "demote"))

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    rows = await _audit(db_session, target.id, "admin.demote")
    assert rows[0].actor_id == actor.id
    assert rows[0].metadata_ == {"from": "superadmin", "to": "admin"}


async def test_last_superadmin_cannot_be_demoted(client, db_session, cleanup_users):
    superadmin = await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    assert await crud_user.count_superadmins(db_session) == 1, "test needs a sole superadmin"

    response = await client.post(_url(superadmin.id, "demote"))

    _assert_error(response, 409, "admin.last_superadmin")
    assert (await _reload(db_session, superadmin.id)).role == UserRole.SUPERADMIN
    response = await client.patch(_url(superadmin.id), json={"role": "member"})
    _assert_error(response, 409, "admin.last_superadmin")


async def test_superadmin_cannot_change_own_role(client, db_session, cleanup_users):
    actor = await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    await _committed(db_session, cleanup_users, factory=create_superadmin)

    _assert_error(await client.post(_url(actor.id, "demote")), 409, "admin.cannot_change_own_role")
    _assert_error(
        await client.patch(_url(actor.id), json={"role": "admin"}),
        409,
        "admin.cannot_change_own_role",
    )


async def test_admin_cannot_change_own_role(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)

    _assert_error(await client.post(_url(admin.id, "demote")), 409, "admin.cannot_change_own_role")
    _assert_error(
        await client.patch(_url(admin.id), json={"role": "member"}),
        409,
        "admin.cannot_change_own_role",
    )
    assert (await _reload(db_session, admin.id)).role == UserRole.ADMIN


# --- ban / unban ------------------------------------------------------------------------------


async def test_ban_revokes_sessions_and_blocks_login(
    client, other_client, db_session, cleanup_users
):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)
    await login_as(other_client, target)
    assert (await other_client.get(ME)).status_code == 200

    response = await client.post(_url(target.id, "ban"))

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert await _active_sessions(db_session, target.id) == 0
    _assert_error(await other_client.get(ME), 401, "auth.not_authenticated")
    login = await other_client.post(
        LOGIN, json={"email": target.email, "password": DEFAULT_PASSWORD}
    )
    _assert_error(login, 403, "auth.account_disabled")
    rows = await _audit(db_session, target.id, "admin.ban")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id


async def test_cannot_ban_self(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)

    _assert_error(await client.post(_url(admin.id, "ban")), 409, "admin.cannot_ban_self")
    _assert_error(
        await client.patch(_url(admin.id), json={"is_active": False}),
        409,
        "admin.cannot_ban_self",
    )
    assert (await _reload(db_session, admin.id)).is_active is True


async def test_admin_cannot_ban_superadmin(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_superadmin)

    _assert_error(await client.post(_url(target.id, "ban")), 403, "auth.forbidden")
    assert (await _reload(db_session, target.id)).is_active is True


async def test_superadmin_can_ban_superadmin(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users, factory=create_superadmin)
    target = await _committed(db_session, cleanup_users, factory=create_superadmin)

    response = await client.post(_url(target.id, "ban"))

    assert response.status_code == 200, response.text
    assert (await _reload(db_session, target.id)).is_active is False


async def test_unban(client, other_client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, is_active=False)

    response = await client.post(_url(target.id, "unban"))

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    await login_as(other_client, target)
    rows = await _audit(db_session, target.id, "admin.unban")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id


async def test_ban_when_already_banned_is_noop(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, is_active=False)

    response = await client.post(_url(target.id, "ban"))

    assert response.status_code == 200, response.text
    assert await _audit(db_session, target.id, "admin.ban") == []


# --- trust / untrust --------------------------------------------------------------------------


async def test_trust_and_untrust(client, other_client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)
    await login_as(other_client, target)

    response = await client.post(_url(target.id, "trust"))

    assert response.status_code == 200, response.text
    assert response.json()["is_trusted"] is True
    assert response.json()["trusted_at"] is not None
    assert (await _reload(db_session, target.id)).trusted_at is not None
    assert (await other_client.get(ME)).json()["is_trusted"] is True

    response = await client.post(_url(target.id, "untrust"))

    assert response.status_code == 200, response.text
    assert response.json()["is_trusted"] is False
    assert (await _reload(db_session, target.id)).trusted_at is None
    assert (await other_client.get(ME)).json()["is_trusted"] is False

    for action in ("admin.trust", "admin.untrust"):
        rows = await _audit(db_session, target.id, action)
        assert len(rows) == 1
        assert rows[0].actor_id == admin.id


async def test_trust_keeps_original_timestamp(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    since = datetime(2026, 1, 1, tzinfo=UTC)
    target = await _committed(db_session, cleanup_users, trusted_at=since)

    response = await client.post(_url(target.id, "trust"))

    assert response.status_code == 200, response.text
    assert (await _reload(db_session, target.id)).trusted_at == since
    assert await _audit(db_session, target.id, "admin.trust") == []


# --- resend verification ----------------------------------------------------------------------


async def test_resend_verification(client, other_client, db_session, outbox, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_user)

    response = await client.post(_url(target.id, "resend-verification"))

    assert response.status_code == 202, response.text
    assert response.json()["code"] == "admin.verification_sent"
    assert len(outbox) == 1
    assert outbox[0].to == target.email
    match = TOKEN_RE.search(outbox[0].text)
    assert match, outbox[0].text
    tokens = await db_session.scalar(select(func.count()).where(EmailToken.user_id == target.id))
    assert tokens == 1
    rows = await _audit(db_session, target.id, "admin.resend_verification")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id

    verified = await other_client.post(VERIFY, json={"token": match.group(1)})
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_verified"] is True


async def test_resend_verification_already_verified(client, db_session, outbox, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.post(_url(target.id, "resend-verification"))

    _assert_error(response, 409, "admin.already_verified")
    assert outbox == []


async def test_resend_verification_email_failure(
    client, db_session, outbox, cleanup_users, monkeypatch
):
    from app.api.v1.endpoints import admin as admin_endpoints

    async def broken_send(**kwargs):
        raise OSError("smtp down")

    monkeypatch.setattr(admin_endpoints, "send_email", broken_send)
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users, factory=create_user)

    response = await client.post(_url(target.id, "resend-verification"))

    _assert_error(response, 502, "admin.email_not_sent")
    assert await _audit(db_session, target.id, "admin.resend_verification") == []
    tokens = await db_session.scalar(select(func.count()).where(EmailToken.user_id == target.id))
    assert tokens == 0


# --- PATCH ------------------------------------------------------------------------------------


async def test_patch_is_active_false_behaves_like_ban(
    client, other_client, db_session, cleanup_users
):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)
    await login_as(other_client, target)

    response = await client.patch(_url(target.id), json={"is_active": False})

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert await _active_sessions(db_session, target.id) == 0
    _assert_error(await other_client.get(ME), 401, "auth.not_authenticated")
    rows = await _audit(db_session, target.id, "admin.ban")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id


async def test_patch_role_and_trust(client, db_session, cleanup_users):
    admin = await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.patch(_url(target.id), json={"role": "admin", "trusted": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "admin"
    assert body["is_trusted"] is True
    promote = await _audit(db_session, target.id, "admin.promote")
    assert promote[0].metadata_ == {"from": "member", "to": "admin"}
    assert promote[0].actor_id == admin.id
    assert len(await _audit(db_session, target.id, "admin.trust")) == 1

    response = await client.patch(_url(target.id), json={"role": "member", "trusted": False})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "member"
    assert response.json()["is_trusted"] is False
    demote = await _audit(db_session, target.id, "admin.demote")
    assert demote[0].metadata_ == {"from": "admin", "to": "member"}
    assert len(await _audit(db_session, target.id, "admin.untrust")) == 1


async def test_patch_role_superadmin_needs_superadmin(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.patch(_url(target.id), json={"role": "superadmin"})

    _assert_error(response, 403, "auth.forbidden")


async def test_patch_failure_rolls_back_earlier_changes(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.patch(_url(target.id), json={"trusted": True, "role": "superadmin"})

    _assert_error(response, 403, "auth.forbidden")
    assert (await _reload(db_session, target.id)).trusted_at is None
    assert await _audit(db_session, target.id, "admin.trust") == []


async def test_patch_empty_body_changes_nothing(client, db_session, cleanup_users):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)

    response = await client.patch(_url(target.id), json={})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "member"


@pytest.mark.parametrize(
    "payload", [{"role": "owner"}, {"role": None}, {"is_active": None}, {"trusted": None}]
)
async def test_patch_validation(client, db_session, cleanup_users, payload):
    await _signed_in(client, db_session, cleanup_users)
    target = await _committed(db_session, cleanup_users)
    response = await client.patch(_url(target.id), json=payload)
    assert response.status_code == 422, response.text


# --- crud -------------------------------------------------------------------------------------


async def test_crud_count_superadmins_ignores_inactive_and_deleted(db_session):
    before = await crud_user.count_superadmins(db_session)
    await create_superadmin(db_session)
    await create_superadmin(db_session, is_active=False)
    await create_superadmin(db_session, deleted_at=datetime.now(UTC))
    assert await crud_user.count_superadmins(db_session) == before + 1


async def test_crud_set_trusted(db_session):
    user = await create_verified_user(db_session)
    now = datetime(2026, 5, 1, tzinfo=UTC)

    assert await crud_user.set_trusted(db_session, user=user, trusted=True, now=now) is True
    assert user.trusted_at == now
    assert await crud_user.set_trusted(db_session, user=user, trusted=True) is False
    assert user.trusted_at == now
    assert await crud_user.set_trusted(db_session, user=user, trusted=False) is True
    assert user.trusted_at is None


async def test_crud_set_active_false_revokes_sessions(db_session):
    from app.crud.session import create_session

    user = await create_verified_user(db_session)
    await create_session(db_session, user_id=user.id, user_agent=None)
    await create_session(db_session, user_id=user.id, user_agent=None)

    assert await crud_user.set_active(db_session, user=user, active=False) is True
    assert user.is_active is False
    assert await _active_sessions(db_session, user.id) == 0
    assert await crud_user.set_active(db_session, user=user, active=False) is False
