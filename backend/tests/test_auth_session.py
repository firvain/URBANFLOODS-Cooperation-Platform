"""Increment 1e: login, logout, ``/me`` GET + PATCH, own sessions, auth dependencies.

The ``client`` runs the app with its own sessions and commits through ``get_db_tx``, so rows it
writes are visible to ``db_session`` and are removed by ``cleanup_users``. Users the test creates
directly are committed (the app cannot see them otherwise) and registered for cleanup too.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from argon2 import PasswordHasher
from sqlalchemy import delete, func, select, update

from app.api.v1.endpoints import auth as auth_endpoints
from app.core import security
from app.core.config import settings
from app.core.deps import CurrentUser, DbTx
from app.core.exceptions import AppError
from app.crud.session import create_session, revoke_session
from app.db import session as db_session_module
from app.db.enums import UserRole
from app.db.models import AuditLog, Organisation, Session, User
from app.main import create_app
from tests.factories import (
    DEFAULT_PASSWORD,
    create_admin,
    create_superadmin,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
LOGIN = f"{API}/auth/login"
LOGOUT = f"{API}/auth/logout"
ME = f"{API}/auth/me"
SESSIONS = f"{API}/auth/me/sessions"
COOKIE = settings.SESSION_COOKIE_NAME
NOT_AUTHENTICATED = "auth.not_authenticated"


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _reload_user(db, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _sessions(db, user_id: int) -> list[Session]:
    stmt = (
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.created_at)
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


async def _uowm_id(db) -> int:
    return await db.scalar(select(Organisation.id).where(Organisation.short_name == "UOWM"))


async def _login(client, email: str, password: str = DEFAULT_PASSWORD, **kwargs):
    return await client.post(LOGIN, json={"email": email, "password": password}, **kwargs)


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_cookie_cleared(response) -> None:
    cookie = response.headers.get("set-cookie", "")
    assert cookie.startswith(f"{COOKIE}="), cookie
    lowered = cookie.lower()
    assert "max-age=0" in lowered or "expires=thu, 01 jan 1970" in lowered, cookie
    assert "path=/" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered


def _assert_validation(response, field: str, code: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail
    if code is not None:
        assert detail["fields"][field] == code


async def _session_cookie_for(db, user: User) -> tuple[Session, str]:
    """A committed session created directly (no login), with its raw token."""
    session, raw = await create_session(db, user_id=user.id, user_agent="Direct/1.0")
    await db.commit()
    return session, raw


# --- login ------------------------------------------------------------------------------------


async def test_login_verified_user(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users, organisation_id=uowm_id)

    response = await _login(client, user.email, headers={"User-Agent": "Device-A/1.0"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == user.id
    assert body["email"] == user.email
    assert body["is_verified"] is True
    assert body["is_trusted"] is False
    assert body["role"] == "member"
    assert body["organisation"]["id"] == uowm_id
    assert body["organisation"]["short_name"] == "UOWM"
    assert "password_hash" not in body and "password" not in response.text

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Path=/" in cookie
    assert "Max-Age=2592000" in cookie
    assert COOKIE in client.cookies

    reloaded = await _reload_user(db_session, user.id)
    assert reloaded.last_login_at is not None
    sessions = await _sessions(db_session, user.id)
    assert len(sessions) == 1
    assert sessions[0].user_agent == "Device-A/1.0"
    assert sessions[0].revoked_at is None

    (entry,) = await _audit(db_session, user.id, "auth.login")
    assert entry.actor_id == user.id
    assert entry.metadata_ == {"user_agent": "Device-A/1.0"}


async def test_login_truncates_user_agent_in_audit(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)

    response = await _login(client, user.email, headers={"User-Agent": "u" * 400})

    assert response.status_code == 200, response.text
    (entry,) = await _audit(db_session, user.id, "auth.login")
    assert entry.metadata_ == {"user_agent": "u" * 255}


async def test_login_wrong_password(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)

    response = await _login(client, user.email, "not-the-right-password")

    _assert_error(response, 401, "auth.invalid_credentials")
    assert "set-cookie" not in response.headers
    assert COOKIE not in client.cookies
    assert await _sessions(db_session, user.id) == []
    assert (await _reload_user(db_session, user.id)).last_login_at is None

    (entry,) = await _audit(db_session, user.id, "auth.login_failed")
    assert entry.actor_id is None
    assert entry.metadata_ == {}
    assert user.email not in str(entry.metadata_)


async def test_login_unknown_email_same_response_and_dummy_verify(
    client, db_session, cleanup_users, monkeypatch
):
    known = await _committed(db_session, cleanup_users)
    wrong_password = await _login(client, known.email, "not-the-right-password")

    calls: list[str] = []
    real_verify = auth_endpoints.verify_password

    def spy(password: str, password_hash: str) -> bool:
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_endpoints, "verify_password", spy)
    before = await db_session.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))
    unknown = "nobody-" + uuid.uuid4().hex[:12] + "@example.org"

    response = await _login(client, unknown, "whatever-password-1")

    assert response.status_code == 401
    assert response.json() == wrong_password.json()
    assert "set-cookie" not in response.headers
    # The dummy argon2 verification ran (keeps timing close to the known-user path).
    assert calls == [auth_endpoints._dummy_hash()]

    stmt = select(AuditLog).where(AuditLog.id > before, AuditLog.action == "auth.login_failed")
    rows = list((await db_session.scalars(stmt)).all())
    try:
        assert len(rows) == 1
        assert rows[0].actor_id is None
        assert rows[0].target_type is None
        assert rows[0].target_id is None
        assert rows[0].metadata_ == {}
    finally:
        # Not tied to any user, so ``cleanup_users`` would not remove it.
        await db_session.execute(delete(AuditLog).where(AuditLog.id.in_([r.id for r in rows])))
        await db_session.commit()


async def test_login_unverified_user_is_allowed(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, factory=create_user)

    response = await _login(client, user.email)

    assert response.status_code == 200, response.text
    assert response.json()["is_verified"] is False
    assert COOKIE in client.cookies


@pytest.mark.parametrize(
    "fields", [{"is_active": False}, {"deleted_at": datetime(2026, 1, 1, tzinfo=UTC)}]
)
async def test_login_disabled_user_correct_password(client, db_session, cleanup_users, fields):
    user = await _committed(db_session, cleanup_users, **fields)

    response = await _login(client, user.email)

    _assert_error(response, 403, "auth.account_disabled")
    assert "set-cookie" not in response.headers
    assert await _sessions(db_session, user.id) == []
    assert (await _reload_user(db_session, user.id)).last_login_at is None
    (entry,) = await _audit(db_session, user.id, "auth.login_failed")
    assert entry.actor_id is None
    assert entry.metadata_ == {}


async def test_login_disabled_user_wrong_password_reveals_nothing(
    client, db_session, cleanup_users
):
    user = await _committed(db_session, cleanup_users, is_active=False)

    response = await _login(client, user.email, "not-the-right-password")

    _assert_error(response, 401, "auth.invalid_credentials")


async def test_login_email_is_case_insensitive(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)

    response = await _login(client, user.email.upper())

    assert response.status_code == 200, response.text
    assert response.json()["id"] == user.id


async def test_login_rehashes_weak_hash(client, db_session, cleanup_users):
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    user = await _committed(db_session, cleanup_users)
    old_hash = weak.hash(DEFAULT_PASSWORD)
    await db_session.execute(update(User).where(User.id == user.id).values(password_hash=old_hash))
    await db_session.commit()
    assert security.password_needs_rehash(old_hash)

    response = await _login(client, user.email)

    assert response.status_code == 200, response.text
    stored = (await _reload_user(db_session, user.id)).password_hash
    assert stored != old_hash
    assert stored.startswith("$argon2id$")
    assert security.verify_password(DEFAULT_PASSWORD, stored)
    assert not security.password_needs_rehash(stored)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "a@example.org", "password": ""}, "password"),
        ({"email": "a@example.org", "password": "p" * 129}, "password"),
        ({"email": "not-an-email", "password": "something-long"}, "email"),
        ({"email": "a@example.org"}, "password"),
    ],
)
async def test_login_validation(client, payload, field):
    _assert_validation(await client.post(LOGIN, json=payload), field)


# --- me / logout ------------------------------------------------------------------------------


async def test_me_without_cookie(client):
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


@pytest.mark.parametrize("raw", ["garbage", "x" * 1000])
async def test_me_with_garbage_cookie(client, raw):
    client.cookies.set(COOKIE, raw)
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


async def test_me_logout_cycle(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users, organisation_id=uowm_id)
    await login_as(client, user)

    me = await client.get(ME)
    assert me.status_code == 200, me.text
    assert me.json()["id"] == user.id
    assert me.json()["organisation"]["short_name"] == "UOWM"

    logout = await client.post(LOGOUT)

    assert logout.status_code == 204
    assert logout.content == b""
    _assert_cookie_cleared(logout)
    assert COOKIE not in client.cookies
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)

    (session,) = await _sessions(db_session, user.id)
    assert session.revoked_at is not None
    (entry,) = await _audit(db_session, user.id, "auth.logout")
    assert entry.actor_id == user.id


async def test_logout_with_stale_cookie_still_works(client, db_session, cleanup_users):
    """The old cookie stops working server-side even if a client kept a copy of it."""
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    raw = client.cookies[COOKIE]
    assert (await client.post(LOGOUT)).status_code == 204

    client.cookies.set(COOKIE, raw)

    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


async def test_logout_without_session_is_204(client):
    response = await client.post(LOGOUT)

    assert response.status_code == 204
    _assert_cookie_cleared(response)


async def test_me_touch_session_is_committed(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    long_ago = datetime.now(UTC) - timedelta(days=3)
    await db_session.execute(
        update(Session).where(Session.user_id == user.id).values(last_seen_at=long_ago)
    )
    await db_session.commit()

    response = await client.get(ME)

    assert response.status_code == 200, response.text
    (session,) = await _sessions(db_session, user.id)
    assert session.last_seen_at > long_ago + timedelta(days=2)


async def test_revoked_session_cookie(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    session, raw = await _session_cookie_for(db_session, user)
    await revoke_session(db_session, session_id=session.id)
    await db_session.commit()
    client.cookies.set(COOKIE, raw)

    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


async def test_expired_session_cookie(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    session, raw = await _session_cookie_for(db_session, user)
    client.cookies.set(COOKIE, raw)
    assert (await client.get(ME)).status_code == 200

    await db_session.execute(
        update(Session)
        .where(Session.id == session.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()

    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


@pytest.mark.parametrize(
    "values", [{"is_active": False}, {"deleted_at": datetime(2026, 1, 1, tzinfo=UTC)}]
)
async def test_session_of_disabled_user_is_rejected_and_revoked(
    client, db_session, cleanup_users, values
):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    await db_session.execute(update(User).where(User.id == user.id).values(**values))
    await db_session.commit()

    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)

    (session,) = await _sessions(db_session, user.id)
    assert session.revoked_at is not None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", ME),
        ("GET", SESSIONS),
        ("DELETE", f"{SESSIONS}/{uuid.uuid4()}"),
    ],
)
async def test_me_routes_require_login(client, method, path):
    kwargs = {"json": {"bio": "x"}} if method == "PATCH" else {}
    response = await client.request(method, path, **kwargs)
    _assert_error(response, 401, NOT_AUTHENTICATED)


# --- PATCH /me --------------------------------------------------------------------------------


async def test_patch_me_updates_display_name_and_bio(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, country="GR")
    await login_as(client, user)

    response = await client.patch(
        ME, json={"display_name": "  Eleni K.  ", "bio": "  Hydrologist in Kozani.  "}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Eleni K."
    assert body["bio"] == "Hydrologist in Kozani."
    assert body["country"] == "GR"  # untouched
    reloaded = await _reload_user(db_session, user.id)
    assert reloaded.display_name == "Eleni K."
    assert reloaded.bio == "Hydrologist in Kozani."

    (entry,) = await _audit(db_session, user.id, "auth.profile_updated")
    assert entry.actor_id == user.id
    assert entry.metadata_ == {"fields": ["bio", "display_name"]}


async def test_patch_me_null_clears_and_omitted_is_kept(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(
        db_session, cleanup_users, organisation_id=uowm_id, country="GR", bio="Old bio"
    )
    await login_as(client, user)

    response = await client.patch(ME, json={"organisation_id": None, "bio": None})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organisation"] is None
    assert body["bio"] is None
    assert body["country"] == "GR"
    reloaded = await _reload_user(db_session, user.id)
    assert reloaded.organisation_id is None
    assert reloaded.bio is None
    assert reloaded.country == "GR"


async def test_patch_me_set_other_clears_organisation_id(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users, organisation_id=uowm_id)
    await login_as(client, user)

    response = await client.patch(ME, json={"organisation_other": "  Town hall  "})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organisation"] is None
    assert body["organisation_other"] == "Town hall"
    (entry,) = await _audit(db_session, user.id, "auth.profile_updated")
    assert entry.metadata_ == {"fields": ["organisation_id", "organisation_other"]}


async def test_patch_me_set_organisation_clears_other(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users, organisation_other="Town hall")
    await login_as(client, user)

    response = await client.patch(ME, json={"organisation_id": uowm_id, "country": "it"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organisation"]["id"] == uowm_id
    assert body["organisation_other"] is None
    assert body["country"] == "IT"


async def test_patch_me_both_organisation_fields_conflict(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.patch(
        ME, json={"organisation_id": uowm_id, "organisation_other": "Town hall"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation.failed"


async def test_me_returns_expertise_other(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, expertise_other="Coastal engineering")
    await login_as(client, user)

    response = await client.get(ME)

    assert response.status_code == 200, response.text
    assert response.json()["expertise_other"] == "Coastal engineering"


async def test_patch_me_sets_expertise_other(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.patch(ME, json={"expertise_other": "  Coastal engineering  "})

    assert response.status_code == 200, response.text
    assert response.json()["expertise_other"] == "Coastal engineering"
    assert (await _reload_user(db_session, user.id)).expertise_other == "Coastal engineering"
    (entry,) = await _audit(db_session, user.id, "auth.profile_updated")
    assert entry.metadata_ == {"fields": ["expertise_other"]}


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_patch_me_clears_expertise_other(client, db_session, cleanup_users, value):
    user = await _committed(db_session, cleanup_users, expertise_other="Coastal engineering")
    await login_as(client, user)

    response = await client.patch(ME, json={"expertise_other": value})

    assert response.status_code == 200, response.text
    assert response.json()["expertise_other"] is None
    assert (await _reload_user(db_session, user.id)).expertise_other is None


async def test_patch_me_omitted_expertise_other_is_kept(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, expertise_other="Coastal engineering")
    await login_as(client, user)

    response = await client.patch(ME, json={"expertise_ids": []})

    assert response.status_code == 200, response.text
    assert response.json()["expertise_other"] == "Coastal engineering"


async def test_patch_me_unknown_organisation(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.patch(ME, json={"organisation_id": 999_999})

    _assert_validation(response, "organisation_id", "not_found")
    assert await _audit(db_session, user.id, "auth.profile_updated") == []


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"locale": "de"}, "locale"),
        ({"locale": None}, "locale"),
        ({"display_name": None}, "display_name"),
        ({"display_name": " x "}, "display_name"),
        ({"display_name": "y" * 121}, "display_name"),
        ({"country": "GRC"}, "country"),
        ({"bio": "b" * 2001}, "bio"),
        ({"organisation_other": "o" * 201}, "organisation_other"),
        ({"expertise_other": "e" * 201}, "expertise_other"),
    ],
)
async def test_patch_me_validation(client, db_session, cleanup_users, payload, field):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_validation(await client.patch(ME, json=payload), field)


async def test_patch_me_locale_and_country_clear(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, country="GR")
    await login_as(client, user)

    response = await client.patch(ME, json={"locale": "el", "country": None})

    assert response.status_code == 200, response.text
    assert response.json()["locale"] == "el"
    assert response.json()["country"] is None


async def test_patch_me_without_changes_writes_no_audit(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, display_name="Same Name")
    await login_as(client, user)

    response = await client.patch(ME, json={"display_name": "Same Name"})

    assert response.status_code == 200, response.text
    assert await _audit(db_session, user.id, "auth.profile_updated") == []


async def test_patch_me_unverified_user_allowed(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, user)

    response = await client.patch(ME, json={"bio": "Not verified yet"})

    assert response.status_code == 200, response.text
    assert response.json()["bio"] == "Not verified yet"


# --- own sessions -----------------------------------------------------------------------------


async def test_list_sessions_two_devices(client, other_client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user, user_agent="Device-A")
    await login_as(other_client, user, user_agent="Device-B")

    response = await client.get(SESSIONS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    items = body["items"]
    assert [item["user_agent"] for item in items] == ["Device-B", "Device-A"]  # newest first
    assert [item["is_current"] for item in items] == [False, True]
    for item in items:
        uuid.UUID(item["id"])
        assert set(item) == {
            "id",
            "created_at",
            "last_seen_at",
            "expires_at",
            "user_agent",
            "is_current",
        }

    from_b = (await other_client.get(SESSIONS)).json()["items"]
    assert [item["is_current"] for item in from_b] == [True, False]


async def test_list_sessions_excludes_revoked(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    session, _ = await _session_cookie_for(db_session, user)
    await revoke_session(db_session, session_id=session.id)
    await db_session.commit()
    await login_as(client, user)

    body = (await client.get(SESSIONS)).json()

    assert body["total"] == 1
    assert body["items"][0]["is_current"] is True


async def test_delete_other_session(client, other_client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user, user_agent="Device-A")
    await login_as(other_client, user, user_agent="Device-B")
    items = (await client.get(SESSIONS)).json()["items"]
    other_id = next(item["id"] for item in items if not item["is_current"])

    response = await client.delete(f"{SESSIONS}/{other_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers
    _assert_error(await other_client.get(ME), 401, NOT_AUTHENTICATED)
    assert (await client.get(ME)).status_code == 200

    (entry,) = await _audit(db_session, user.id, "auth.session_revoked")
    assert entry.actor_id == user.id
    assert entry.metadata_ == {"session_id": other_id, "current": False}


async def test_delete_unknown_session(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.delete(f"{SESSIONS}/{uuid.uuid4()}")

    _assert_error(response, 404, "auth.session_not_found")


async def test_delete_invalid_session_id_is_validation_error(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    # Path parameter errors are keyed ``path.<name>`` by the shared validation handler.
    _assert_validation(await client.delete(f"{SESSIONS}/not-a-uuid"), "path.session_id")


async def test_delete_another_users_session(client, other_client, db_session, cleanup_users):
    alice = await _committed(db_session, cleanup_users)
    bob = await _committed(db_session, cleanup_users)
    await login_as(client, alice)
    await login_as(other_client, bob)
    (bob_session,) = await _sessions(db_session, bob.id)

    response = await client.delete(f"{SESSIONS}/{bob_session.id}")

    _assert_error(response, 404, "auth.session_not_found")
    assert (await other_client.get(ME)).status_code == 200
    (bob_session,) = await _sessions(db_session, bob.id)
    assert bob_session.revoked_at is None


async def test_delete_current_session_clears_cookie(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    (current,) = (await client.get(SESSIONS)).json()["items"]

    response = await client.delete(f"{SESSIONS}/{current['id']}")

    assert response.status_code == 204
    _assert_cookie_cleared(response)
    assert COOKIE not in client.cookies
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)
    (entry,) = await _audit(db_session, user.id, "auth.session_revoked")
    assert entry.metadata_ == {"session_id": current["id"], "current": True}


# --- role dependencies (unit) -----------------------------------------------------------------


def _fake_user(role: UserRole = UserRole.MEMBER, *, is_verified: bool = True) -> User:
    return User(
        email="fake@example.org",
        password_hash="x",
        display_name="Fake",
        role=role,
        is_verified=is_verified,
        is_active=True,
    )


async def _raises(dependency, user, status: int, code: str) -> None:
    with pytest.raises(AppError) as excinfo:
        await dependency(user)
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


def _fake_request(**state) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(**state))


async def test_require_user():
    from app.core.deps import require_user

    with pytest.raises(AppError) as excinfo:
        await require_user(_fake_request(), None)
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == NOT_AUTHENTICATED
    assert excinfo.value.keep_changes is False

    user = _fake_user(is_verified=False)
    assert await require_user(_fake_request(), user) is user


async def test_require_user_keeps_revocation_of_disabled_session():
    from app.core.deps import require_user

    with pytest.raises(AppError) as excinfo:
        await require_user(_fake_request(revoked_disabled_session=True), None)
    assert excinfo.value.status_code == 401
    assert excinfo.value.keep_changes is True


async def test_require_verified():
    from app.core.deps import require_verified

    await _raises(require_verified, _fake_user(is_verified=False), 403, "auth.email_not_verified")
    user = _fake_user()
    assert await require_verified(user) is user


async def test_require_admin():
    from app.core.deps import require_admin

    await _raises(require_admin, _fake_user(UserRole.MEMBER), 403, "auth.forbidden")
    for role in (UserRole.ADMIN, UserRole.SUPERADMIN):
        user = _fake_user(role)
        assert await require_admin(user) is user


async def test_require_superadmin():
    from app.core.deps import require_superadmin

    for role in (UserRole.MEMBER, UserRole.ADMIN):
        await _raises(require_superadmin, _fake_user(role), 403, "auth.forbidden")
    user = _fake_user(UserRole.SUPERADMIN)
    assert await require_superadmin(user) is user


async def test_role_factories_and_me(client, db_session, cleanup_users):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    superadmin = await _committed(db_session, cleanup_users, factory=create_superadmin)

    await login_as(client, admin)
    assert (await client.get(ME)).json()["role"] == "admin"
    await client.post(LOGOUT)
    await login_as(client, superadmin)
    assert (await client.get(ME)).json()["role"] == "superadmin"


async def test_auth_dependency_shares_the_request_transaction(db_session, cleanup_users):
    """``get_current_user`` and the endpoint get the same cached ``DbTx`` session.

    (Annotations in this module are strings, so ``CurrentUser``/``DbTx`` are module imports.)
    """
    app = create_app()

    @app.get("/_probe")
    async def probe(user: CurrentUser, db: DbTx) -> dict:
        return {"user": user is not None, "same_session": user is not None and user in db}

    user = await _committed(db_session, cleanup_users)
    _, raw = await _session_cookie_for(db_session, user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={COOKIE: raw}
    ) as ac:
        response = await ac.get("/_probe")

    assert response.json() == {"user": True, "same_session": True}


# --- review fixes: one connection, keep_changes, re-login, fewer queries ----------------------


def _probe_app():
    """A fresh app with an optional-user route (200 whether or not anyone is signed in) and two
    routes that write an audit row and then raise, with and without ``keep_changes``."""
    app = create_app()

    @app.get("/_optional")
    async def optional(user: CurrentUser) -> dict:
        return {"user": user is not None}

    @app.post("/_raise/{keep}")
    async def raise_after_write(keep: bool, db: DbTx) -> dict:
        from app.crud.audit import log_action

        await log_action(db, actor_id=None, action=f"test.keep_{keep}")
        raise AppError(409, "test.conflict", keep_changes=keep)

    return app


async def _probe(app, raw: str | None, method: str, path: str) -> httpx.Response:
    cookies = {COOKIE: raw} if raw else None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as ac:
        return await ac.request(method, path)


@pytest.mark.parametrize("keep", [True, False])
async def test_app_error_keep_changes_commits_the_request_transaction(db_session, keep):
    response = await _probe(_probe_app(), None, "POST", f"/_raise/{str(keep).lower()}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "test.conflict"
    rows = list(
        (await db_session.scalars(select(AuditLog).where(AuditLog.action == f"test.keep_{keep}")))
    )
    try:
        assert len(rows) == (1 if keep else 0)
    finally:
        await db_session.execute(delete(AuditLog).where(AuditLog.action == f"test.keep_{keep}"))
        await db_session.commit()


async def _disable_with_session(db, cleanup_users) -> tuple[User, Session, str]:
    user = await _committed(db, cleanup_users)
    session, raw = await _session_cookie_for(db, user)
    await db.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db.commit()
    return user, session, raw


async def test_disabled_user_revocation_persists_when_endpoint_401s(
    client, db_session, cleanup_users, monkeypatch
):
    user, session, raw = await _disable_with_session(db_session, cleanup_users)
    opened: list[object] = []
    real_factory = db_session_module.AsyncSessionLocal

    def counting_factory(*args, **kwargs):
        opened.append(object())
        return real_factory(*args, **kwargs)

    monkeypatch.setattr("app.core.deps.AsyncSessionLocal", counting_factory)
    client.cookies.set(COOKIE, raw)

    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)

    assert len(opened) == 1  # only the request's own DbTx session; no second connection
    (stored,) = await _sessions(db_session, user.id)
    assert stored.revoked_at is not None


async def test_disabled_user_revocation_persists_on_optional_user_route(db_session, cleanup_users):
    user, session, raw = await _disable_with_session(db_session, cleanup_users)

    response = await _probe(_probe_app(), raw, "GET", "/_optional")

    assert response.status_code == 200
    assert response.json() == {"user": False}
    (stored,) = await _sessions(db_session, user.id)
    assert stored.revoked_at is not None


async def test_relogin_on_same_client_revokes_previous_session(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    first_raw = client.cookies[COOKIE]

    await login_as(client, user)

    assert client.cookies[COOKIE] != first_raw
    body = (await client.get(SESSIONS)).json()
    assert body["total"] == 1
    assert body["items"][0]["is_current"] is True

    client.cookies.set(COOKIE, first_raw)
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


async def test_login_as_another_account_revokes_the_previous_session(
    client, db_session, cleanup_users
):
    first = await _committed(db_session, cleanup_users)
    second = await _committed(db_session, cleanup_users)
    await login_as(client, first)
    first_raw = client.cookies[COOKIE]

    await login_as(client, second)

    assert (await client.get(ME)).json()["id"] == second.id
    active = await db_session.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == first.id, Session.revoked_at.is_(None))
    )
    assert active == 0
    client.cookies.set(COOKIE, first_raw)
    _assert_error(await client.get(ME), 401, NOT_AUTHENTICATED)


async def test_failed_relogin_keeps_existing_session(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await _login(client, user.email, "not-the-right-password")

    _assert_error(response, 401, "auth.invalid_credentials")
    assert (await client.get(ME)).status_code == 200


async def test_me_is_one_select_and_no_write_within_touch_interval(
    client, db_session, cleanup_users
):
    from sqlalchemy import event

    uowm_id = await _uowm_id(db_session)
    user = await _committed(db_session, cleanup_users, organisation_id=uowm_id)
    await login_as(client, user)
    (before,) = await _sessions(db_session, user.id)

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    engine = db_session_module.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = await client.get(ME)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200, response.text
    assert response.json()["organisation"]["short_name"] == "UOWM"
    assert statements == ["SELECT"], statements
    (after,) = await _sessions(db_session, user.id)
    assert after.last_seen_at == before.last_seen_at


def test_dummy_hash_is_lazy_and_cached():
    assert not hasattr(auth_endpoints, "DUMMY_PASSWORD_HASH")
    first = auth_endpoints._dummy_hash()
    assert first.startswith("$argon2id$")
    assert auth_endpoints._dummy_hash() is first
