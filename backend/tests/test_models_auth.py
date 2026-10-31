"""Increment 1a: auth tables (organisations, users, sessions, email_tokens,
notification_preferences, audit_log) and the seeded partner organisations.

All tests run against the session database migrated to head by ``conftest.py``. Every test works
inside the ``db_session`` transaction and only flushes, so the fixture's rollback leaves no rows
behind (ON DELETE behaviour is enforced by Postgres at statement time, so it is visible before
commit).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.db.enums import DigestFrequency, OrganisationType, TokenPurpose, UserRole
from app.db.models import (
    AuditLog,
    EmailToken,
    NotificationPreference,
    Organisation,
    Session,
    User,
)

PROJECT_COUNTRIES = {"AL", "BA", "GR", "HR", "IT", "MK", "RS", "SI"}


async def _make_user(db, email: str = "user@example.org", **kwargs) -> User:
    user = User(email=email, password_hash="not-a-real-hash", display_name="Test User", **kwargs)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _uowm(db) -> Organisation:
    return (
        await db.execute(select(Organisation).where(Organisation.short_name == "UOWM"))
    ).scalar_one()


async def test_migration_0002_seeds_22_organisations(db_session):
    total = await db_session.scalar(text("SELECT count(*) FROM organisations"))
    assert total == 22

    by_type = dict(
        (
            await db_session.execute(
                text("SELECT type::text, count(*) FROM organisations GROUP BY type")
            )
        ).all()
    )
    assert by_type == {"PP": 11, "AP": 11}

    uowm = await _uowm(db_session)
    assert uowm.country == "GR"
    assert uowm.website == "https://www.uowm.gr/en/"
    assert uowm.type is OrganisationType.PP
    assert uowm.is_partner is True
    assert uowm.sort_order == 1

    countries = set((await db_session.scalars(select(Organisation.country).distinct())).all())
    assert countries == PROJECT_COUNTRIES


async def test_user_email_is_case_insensitive_unique(db_session):
    await _make_user(db_session, email="Alice@Example.org")

    db_session.add(User(email="alice@example.org", password_hash="x", display_name="Alice 2"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_defaults(db_session):
    user = await _make_user(db_session)

    assert user.role is UserRole.MEMBER
    assert user.is_verified is False
    assert user.is_active is True
    assert user.trusted_at is None
    assert user.locale == "en"
    assert user.deleted_at is None
    assert isinstance(user.created_at, datetime) and user.created_at.tzinfo is not None
    assert isinstance(user.updated_at, datetime) and user.updated_at.tzinfo is not None

    prefs = NotificationPreference(user_id=user.id)
    db_session.add(prefs)
    await db_session.flush()
    await db_session.refresh(prefs)
    assert prefs.reply_to_my_thread is True
    assert prefs.comment_on_my_post is True
    assert prefs.reply_to_my_reply is True
    assert prefs.admin_digest is True
    assert prefs.moderation_decisions is True
    assert prefs.digest_frequency is DigestFrequency.DAILY
    await db_session.refresh(user, ["notification_preferences"])
    assert user.notification_preferences is prefs


async def test_user_organisation_relationship(db_session):
    uowm = await _uowm(db_session)
    user = await _make_user(db_session, organisation_id=uowm.id)

    loaded = (
        await db_session.execute(
            select(User).where(User.id == user.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    await db_session.refresh(loaded, ["organisation"])
    assert loaded.organisation.short_name == "UOWM"

    await db_session.execute(delete(Organisation).where(Organisation.id == uowm.id))
    org_id = await db_session.scalar(
        text("SELECT organisation_id FROM users WHERE id = :id"), {"id": user.id}
    )
    assert org_id is None


async def test_session_cascades_on_user_delete(db_session):
    user = await _make_user(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Session(user_id=user.id, token_hash="a" * 64, expires_at=now + timedelta(days=30)),
            EmailToken(
                user_id=user.id,
                purpose=TokenPurpose.VERIFY_EMAIL,
                token_hash="b" * 64,
                expires_at=now + timedelta(hours=48),
            ),
            NotificationPreference(user_id=user.id),
        ]
    )
    await db_session.flush()

    async def counts() -> tuple[int, int, int]:
        params = {"id": user.id}
        return (
            await db_session.scalar(
                text("SELECT count(*) FROM sessions WHERE user_id = :id"), params
            ),
            await db_session.scalar(
                text("SELECT count(*) FROM email_tokens WHERE user_id = :id"), params
            ),
            await db_session.scalar(
                text("SELECT count(*) FROM notification_preferences WHERE user_id = :id"), params
            ),
        )

    assert await counts() == (1, 1, 1)

    await db_session.execute(delete(User).where(User.id == user.id))

    assert await counts() == (0, 0, 0)


async def test_session_token_hash_unique(db_session):
    user = await _make_user(db_session)
    expires = datetime.now(UTC) + timedelta(days=1)
    first = Session(user_id=user.id, token_hash="c" * 64, expires_at=expires)
    db_session.add(first)
    await db_session.flush()
    await db_session.refresh(first)
    assert isinstance(first.id, uuid.UUID)
    assert first.created_at is not None and first.last_seen_at is not None
    assert first.revoked_at is None

    db_session.add(Session(user_id=user.id, token_hash="c" * 64, expires_at=expires))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_audit_log_actor_set_null_on_user_delete(db_session):
    user = await _make_user(db_session)
    entry = AuditLog(
        actor_id=user.id,
        action="user.promote",
        target_type="user",
        target_id=user.id,
        metadata_={"from": "member", "to": "admin", "nested": {"n": 1}},
    )
    db_session.add(entry)
    await db_session.flush()
    entry_id = entry.id

    await db_session.execute(delete(User).where(User.id == user.id))

    row = (
        await db_session.execute(
            text("SELECT actor_id, metadata FROM audit_log WHERE id = :id"), {"id": entry_id}
        )
    ).one()
    assert row.actor_id is None
    meta = row.metadata
    if isinstance(meta, str):  # asyncpg returns jsonb as text unless a codec is registered
        import json

        meta = json.loads(meta)
    assert meta == {"from": "member", "to": "admin", "nested": {"n": 1}}

    bare = AuditLog(action="auth.consent")
    db_session.add(bare)
    await db_session.flush()
    await db_session.refresh(bare)
    assert bare.metadata_ == {}


async def test_updated_at_changes_on_update(db_session):
    # now() is fixed for the whole transaction, so start from a timestamp in the past to see
    # the onupdate fire without committing.
    past = datetime(2020, 1, 1, tzinfo=UTC)
    user = await _make_user(db_session, created_at=past, updated_at=past)
    assert user.updated_at == past

    user.display_name = "Renamed"
    await db_session.flush()
    await db_session.refresh(user)

    assert user.created_at == past
    assert user.updated_at > user.created_at


async def test_enum_values_match_python_enums(db_session):
    expected = {
        "user_role": UserRole,
        "token_purpose": TokenPurpose,
        "organisation_type": OrganisationType,
        "digest_frequency": DigestFrequency,
    }
    for pg_type, py_enum in expected.items():
        values = await db_session.scalar(text(f"SELECT enum_range(NULL::{pg_type})::text[]"))
        assert values == [member.value for member in py_enum], pg_type
