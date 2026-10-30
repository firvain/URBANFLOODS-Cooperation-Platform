"""Async test factories: create rows directly in the database (bypassing the API).

Factories only ``flush``. Tests that drive the HTTP API must ``commit`` the session so the app,
which uses its own sessions, can see the rows; register committed users with the
``cleanup_users`` fixture so they are deleted afterwards.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.enums import UserRole
from app.db.models import NotificationPreference, User

DEFAULT_PASSWORD = "correct-horse-battery-staple"


def unique_email(prefix: str = "user") -> str:
    """A fresh address, so tests never collide even if a cleanup was missed."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.org"


async def create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Test User",
    is_verified: bool = False,
    is_active: bool = True,
    role: UserRole = UserRole.MEMBER,
    **fields: Any,
) -> User:
    """Insert a user (with notification preferences) and flush. Unverified by default."""
    user = User(
        email=email or unique_email(),
        password_hash=hash_password(password),
        display_name=display_name,
        is_verified=is_verified,
        is_active=is_active,
        role=role,
        **fields,
    )
    user.notification_preferences = NotificationPreference()
    db.add(user)
    await db.flush()
    return user


async def create_verified_user(db: AsyncSession, **kwargs: Any) -> User:
    """A user whose email address is already verified."""
    return await create_user(db, is_verified=True, **kwargs)
