"""Increment 1b: server-side session data access (``app.crud.session``).

Every test runs inside the ``db_session`` transaction and only flushes; the fixture rolls back.
Time is controlled by passing ``now`` explicitly (no clock freezing around asyncpg).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_token
from app.crud.session import (
    TOUCH_INTERVAL,
    create_session,
    delete_expired_sessions,
    get_active_session_by_raw_token,
    list_sessions_for_user,
    revoke_all_sessions_for_user,
    revoke_session,
    touch_session,
)
from app.db.models import Session, User

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
TTL = timedelta(days=settings.SESSION_TTL_DAYS)


async def _make_user(db, email: str = "session-user@example.org") -> User:
    user = User(email=email, password_hash="not-a-real-hash", display_name="Session User")
    db.add(user)
    await db.flush()
    return user


async def test_create_session_stores_only_the_hash(db_session):
    user = await _make_user(db_session)

    session, raw = await create_session(db_session, user_id=user.id, user_agent="UA/1.0", now=T0)

    assert isinstance(session.id, uuid.UUID)
    assert session.user_id == user.id
    assert session.token_hash == hash_token(raw)
    assert session.token_hash != raw
    assert session.expires_at == T0 + TTL
    assert session.last_seen_at == T0
    assert session.user_agent == "UA/1.0"
    assert session.revoked_at is None

    stored_raw = await db_session.scalar(
        select(func.count()).select_from(Session).where(Session.token_hash == raw)
    )
    assert stored_raw == 0


async def test_create_session_truncates_long_user_agent(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent="x" * 400, now=T0)
    assert len(session.user_agent) == 255


async def test_get_active_session_by_raw_token_loads_user(db_session):
    user = await _make_user(db_session, email="loader@example.org")
    _, raw = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)
    db_session.expunge_all()  # force a real load, not the identity map

    found = await get_active_session_by_raw_token(
        db_session, raw_token=raw, now=T0 + timedelta(hours=1)
    )

    assert found is not None
    assert "user" in found.__dict__  # eagerly loaded, no lazy load in async
    assert found.user.email == "loader@example.org"


async def test_get_active_session_wrong_token(db_session):
    user = await _make_user(db_session)
    await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    assert await get_active_session_by_raw_token(db_session, raw_token="nope", now=T0) is None


async def test_get_active_session_revoked(db_session):
    user = await _make_user(db_session)
    session, raw = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    assert await revoke_session(db_session, session_id=session.id, now=T0) is True

    assert await get_active_session_by_raw_token(db_session, raw_token=raw, now=T0) is None


async def test_get_active_session_expired(db_session):
    user = await _make_user(db_session)
    _, raw = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    just_before = T0 + TTL - timedelta(seconds=1)
    assert await get_active_session_by_raw_token(db_session, raw_token=raw, now=just_before)
    assert await get_active_session_by_raw_token(db_session, raw_token=raw, now=T0 + TTL) is None


async def test_touch_within_a_day_keeps_expiry(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    later = T0 + timedelta(hours=12)
    await touch_session(db_session, session=session, now=later)
    await db_session.refresh(session)

    assert session.last_seen_at == later
    assert session.expires_at == T0 + TTL


async def test_touch_after_two_days_extends_expiry(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    later = T0 + timedelta(days=2)
    await touch_session(db_session, session=session, now=later)
    await db_session.refresh(session)

    assert session.last_seen_at == later
    assert session.expires_at == later + TTL


async def test_frequent_touches_still_slide_the_expiry(db_session):
    # An active user touching every hour must still have the expiry slide forward.
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    for hour in range(1, 50):
        await touch_session(db_session, session=session, now=T0 + timedelta(hours=hour))
    await db_session.refresh(session)

    assert session.expires_at > T0 + TTL + timedelta(days=1)


async def test_revoke_session_returns_false_for_unknown_or_already_revoked(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    assert await revoke_session(db_session, session_id=uuid.uuid4(), now=T0) is False
    assert await revoke_session(db_session, session_id=session.id, now=T0) is True
    assert await revoke_session(db_session, session_id=session.id, now=T0) is False
    await db_session.refresh(session)
    assert session.revoked_at == T0


async def test_revoke_session_scoped_to_user(db_session):
    owner = await _make_user(db_session, email="owner@example.org")
    other = await _make_user(db_session, email="other@example.org")
    session, _ = await create_session(db_session, user_id=owner.id, user_agent=None, now=T0)

    assert await revoke_session(db_session, session_id=session.id, user_id=other.id) is False
    assert await revoke_session(db_session, session_id=session.id, user_id=owner.id) is True


async def test_revoke_all_except_current_keeps_exactly_one(db_session):
    user = await _make_user(db_session)
    other = await _make_user(db_session, email="bystander@example.org")
    current, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)
    for _ in range(3):
        await create_session(db_session, user_id=user.id, user_agent=None, now=T0)
    await create_session(db_session, user_id=other.id, user_agent=None, now=T0)

    revoked = await revoke_all_sessions_for_user(
        db_session, user_id=user.id, now=T0, except_session_id=current.id
    )

    assert revoked == 3
    active = await list_sessions_for_user(db_session, user_id=user.id, now=T0)
    assert [s.id for s in active] == [current.id]
    assert len(await list_sessions_for_user(db_session, user_id=other.id, now=T0)) == 1


async def test_revoke_all_without_exception(db_session):
    user = await _make_user(db_session)
    for _ in range(2):
        await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    assert await revoke_all_sessions_for_user(db_session, user_id=user.id, now=T0) == 2
    assert await list_sessions_for_user(db_session, user_id=user.id, now=T0) == []


async def test_list_sessions_newest_first_excludes_revoked_and_expired(db_session):
    user = await _make_user(db_session)
    oldest, _ = await create_session(db_session, user_id=user.id, user_agent="a", now=T0)
    middle, _ = await create_session(
        db_session, user_id=user.id, user_agent="b", now=T0 + timedelta(hours=1)
    )
    newest, _ = await create_session(
        db_session, user_id=user.id, user_agent="c", now=T0 + timedelta(hours=2)
    )
    expired, _ = await create_session(
        db_session, user_id=user.id, user_agent="d", now=T0 - TTL - timedelta(days=1)
    )
    await revoke_session(db_session, session_id=middle.id, now=T0 + timedelta(hours=3))

    sessions = await list_sessions_for_user(
        db_session, user_id=user.id, now=T0 + timedelta(hours=4)
    )

    assert [s.id for s in sessions] == [newest.id, oldest.id]
    assert expired.id not in {s.id for s in sessions}


async def test_delete_expired_sessions_removes_only_old_ones(db_session):
    user = await _make_user(db_session)
    now = T0 + timedelta(days=100)

    active, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=now)
    # Expired 3 days ago: kept (within the 7-day grace).
    recently_expired, _ = await create_session(
        db_session, user_id=user.id, user_agent=None, now=now - TTL - timedelta(days=3)
    )
    # Expired 10 days ago: deleted.
    long_expired, _ = await create_session(
        db_session, user_id=user.id, user_agent=None, now=now - TTL - timedelta(days=10)
    )
    # Revoked 2 days ago: kept.
    recently_revoked, _ = await create_session(
        db_session, user_id=user.id, user_agent=None, now=now - timedelta(days=5)
    )
    await revoke_session(db_session, session_id=recently_revoked.id, now=now - timedelta(days=2))
    # Revoked 8 days ago (otherwise unexpired): deleted.
    long_revoked, _ = await create_session(
        db_session, user_id=user.id, user_agent=None, now=now - timedelta(days=9)
    )
    await revoke_session(db_session, session_id=long_revoked.id, now=now - timedelta(days=8))
    kept_ids = {active.id, recently_expired.id, recently_revoked.id}

    deleted = await delete_expired_sessions(db_session, now=now)

    assert deleted == 2
    remaining = set(
        (await db_session.scalars(select(Session.id).where(Session.user_id == user.id))).all()
    )
    assert remaining == kept_ids


async def test_delete_expired_sessions_custom_window(db_session):
    user = await _make_user(db_session)
    now = T0 + timedelta(days=100)
    await create_session(
        db_session, user_id=user.id, user_agent=None, now=now - TTL - timedelta(days=3)
    )

    assert await delete_expired_sessions(db_session, now=now) == 0
    assert await delete_expired_sessions(db_session, now=now, older_than_days=1) == 1


async def test_touch_within_interval_does_not_write(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    wrote = await touch_session(db_session, session=session, now=T0 + timedelta(minutes=4))
    await db_session.refresh(session)

    assert wrote is False
    assert session.last_seen_at == T0
    assert session.expires_at == T0 + TTL


async def test_touch_after_interval_writes(db_session):
    user = await _make_user(db_session)
    session, _ = await create_session(db_session, user_id=user.id, user_agent=None, now=T0)

    later = T0 + TOUCH_INTERVAL + timedelta(seconds=1)
    wrote = await touch_session(db_session, session=session, now=later)
    await db_session.refresh(session)

    assert wrote is True
    assert session.last_seen_at == later


async def test_get_active_session_loads_user_organisation_and_preferences(db_session):
    from app.db.models import NotificationPreference

    user = await _make_user(db_session, email="session-eager@example.org")
    user.notification_preferences = NotificationPreference()
    await db_session.flush()
    _, raw = await create_session(db_session, user_id=user.id, user_agent=None)
    db_session.expunge_all()

    session = await get_active_session_by_raw_token(db_session, raw_token=raw)

    assert "user" in session.__dict__
    assert "organisation" in session.user.__dict__
    assert "notification_preferences" in session.user.__dict__
    assert session.user.notification_preferences is not None
