"""User data access. Never commits; the caller (``get_db_tx``) does."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import AppError, validation_error
from app.core.security import hash_password, validate_password_policy
from app.db.models import NotificationPreference, Organisation, User

EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"


async def get_user_by_email(db: AsyncSession, *, email: str) -> User | None:
    """Case-insensitive lookup (``users.email`` is CITEXT). Includes inactive/deleted users."""
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, *, user_id: int) -> User | None:
    """The user with ``organisation`` and ``notification_preferences`` eagerly loaded."""
    stmt = (
        select(User)
        .options(joinedload(User.organisation), joinedload(User.notification_preferences))
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).unique().scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    organisation_id: int | None = None,
    organisation_other: str | None = None,
    country: str | None = None,
    locale: str = "en",
) -> User:
    """Create an unverified member with default notification preferences.

    Raises ``PasswordPolicyError`` for a weak password, ``AppError`` 422 (``fields.
    organisation_id = "not_found"``) for an unknown organisation, and ``AppError`` 409
    ``auth.email_taken`` if the address (any case) is already registered.
    """
    validate_password_policy(password)
    if organisation_id is not None and await db.get(Organisation, organisation_id) is None:
        raise validation_error({"organisation_id": "not_found"})

    # argon2 is deliberately slow; keep it off the event loop.
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        organisation_id=organisation_id,
        organisation_other=organisation_other,
        country=country,
        locale=locale,
    )
    user.notification_preferences = NotificationPreference()
    try:
        # A savepoint keeps the outer transaction usable if the insert fails.
        async with db.begin_nested():
            db.add(user)
    except IntegrityError as exc:
        if EMAIL_UNIQUE_CONSTRAINT in str(exc.orig):
            raise AppError(
                409, "auth.email_taken", "An account with this email address already exists."
            ) from None
        raise
    # Reload so server defaults (role, flags, timestamps) and relationships are populated.
    loaded = await get_user_by_id(db, user_id=user.id)
    assert loaded is not None
    return loaded


async def mark_verified(db: AsyncSession, *, user: User, now: datetime | None = None) -> None:
    """Mark the user's email address as verified. ``now`` is accepted for API symmetry; there
    is no ``verified_at`` column (the audit log records when)."""
    user.is_verified = True
    await db.flush()
