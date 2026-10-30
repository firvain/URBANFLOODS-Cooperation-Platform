"""Opaque server-side sessions.

The client holds the raw token (cookie); only its SHA-256 hash is stored. Activity is recorded at
most every ``TOUCH_INTERVAL`` and the expiry slides forward at most once per day, to limit
writes. Never commits; the caller does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.security import generate_token, hash_token, session_expiry
from app.db.models import Session, User

USER_AGENT_MAX_LENGTH = 255
# Sliding expiry is pushed forward only when it would move by more than this.
SLIDE_THRESHOLD = timedelta(days=1)
# ``last_seen_at`` is written only when it is older than this (no UPDATE on every request).
TOUCH_INTERVAL = timedelta(minutes=5)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _is_active(now: datetime):
    return Session.revoked_at.is_(None), Session.expires_at > now


async def create_session(
    db: AsyncSession, *, user_id: int, user_agent: str | None, now: datetime | None = None
) -> tuple[Session, str]:
    """Create a session; returns ``(session, raw_token)``. Only the token hash is stored."""
    now = _now(now)
    raw_token, token_hash = generate_token()
    session = Session(
        user_id=user_id,
        token_hash=token_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=session_expiry(now),
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def get_active_session_by_raw_token(
    db: AsyncSession, *, raw_token: str, now: datetime | None = None
) -> Session | None:
    """The unrevoked, unexpired session for a raw token, with ``.user`` and the user's
    ``organisation``, ``notification_preferences`` and ``expertise`` eagerly loaded, all in one
    query (``GET /auth/me`` is a single SELECT; the expertise join adds at most 8 rows).

    The user's own state (``is_active``, ``deleted_at``, ``is_verified``) is checked by the
    auth dependencies, not here.
    """
    user = joinedload(Session.user)
    stmt = (
        select(Session)
        .options(
            user.joinedload(User.organisation),
            user.joinedload(User.notification_preferences),
            user.joinedload(User.expertise),
        )
        .where(Session.token_hash == hash_token(raw_token), *_is_active(_now(now)))
    )
    return (await db.execute(stmt)).unique().scalar_one_or_none()


async def touch_session(db: AsyncSession, *, session: Session, now: datetime | None = None) -> bool:
    """Record activity and slide the expiry. Returns True if anything was written.

    Nothing is written while ``last_seen_at`` is at most ``TOUCH_INTERVAL`` old. Otherwise
    ``last_seen_at`` is set, and ``expires_at`` is moved to ``session_expiry(now)`` only when
    that would extend it by more than a day, i.e. the expiry is refreshed at most once a day
    however often the session is used.
    """
    now = _now(now)
    if now - session.last_seen_at <= TOUCH_INTERVAL:
        return False
    session.last_seen_at = now
    new_expiry = session_expiry(now)
    if new_expiry - session.expires_at > SLIDE_THRESHOLD:
        session.expires_at = new_expiry
    await db.flush()
    return True


async def revoke_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Revoke one session. True if a not-yet-revoked session was revoked.

    Pass ``user_id`` to restrict the revocation to that user's sessions (``DELETE
    /me/sessions/{id}``), so one user cannot revoke another's session by id.
    """
    stmt = update(Session).where(Session.id == session_id, Session.revoked_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(Session.user_id == user_id)
    stmt = stmt.values(revoked_at=_now(now)).returning(Session.id)
    return (await db.execute(stmt)).first() is not None


async def revoke_all_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
    except_session_id: uuid.UUID | None = None,
) -> int:
    """Revoke every unrevoked session of a user (optionally keeping one). Returns the count."""
    stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_session_id is not None:
        stmt = stmt.where(Session.id != except_session_id)
    stmt = stmt.values(revoked_at=_now(now)).returning(Session.id)
    return len((await db.execute(stmt)).all())


async def list_sessions_for_user(
    db: AsyncSession, *, user_id: int, now: datetime | None = None
) -> list[Session]:
    """Active sessions of a user, newest first."""
    stmt = (
        select(Session)
        .where(Session.user_id == user_id, *_is_active(_now(now)))
        .order_by(Session.created_at.desc(), Session.id)
    )
    return list((await db.scalars(stmt)).all())


async def delete_expired_sessions(
    db: AsyncSession, *, now: datetime | None = None, older_than_days: int = 7
) -> int:
    """Hard-delete sessions that expired or were revoked more than ``older_than_days`` ago."""
    cutoff = _now(now) - timedelta(days=older_than_days)
    stmt = (
        delete(Session)
        .where(or_(Session.expires_at < cutoff, Session.revoked_at < cutoff))
        .returning(Session.id)
    )
    return len((await db.execute(stmt)).all())
