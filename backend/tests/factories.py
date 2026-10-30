"""Async test factories: create rows directly in the database (bypassing the API).

Factories only ``flush``. Tests that drive the HTTP API must ``commit`` the session so the app,
which uses its own sessions, can see the rows; register committed users with the
``cleanup_users`` fixture so they are deleted afterwards.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.enums import OrganisationType, UserRole
from app.db.models import NotificationPreference, Organisation, User

if TYPE_CHECKING:
    import httpx

DEFAULT_PASSWORD = "correct-horse-battery-staple"
LOGIN_PATH = f"{settings.API_V1_PREFIX}/auth/login"


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


async def create_admin(db: AsyncSession, **kwargs: Any) -> User:
    """A verified ``admin``."""
    return await create_verified_user(db, role=UserRole.ADMIN, **kwargs)


async def create_superadmin(db: AsyncSession, **kwargs: Any) -> User:
    """A verified ``superadmin``."""
    return await create_verified_user(db, role=UserRole.SUPERADMIN, **kwargs)


async def login_as(
    client: httpx.AsyncClient,
    user: User,
    *,
    password: str = DEFAULT_PASSWORD,
    user_agent: str | None = None,
) -> httpx.Response:
    """Log ``user`` in through ``POST /auth/login``; the session cookie stays on ``client``.

    The user must be committed first (the app uses its own database sessions).
    """
    headers = {"User-Agent": user_agent} if user_agent else None
    response = await client.post(
        LOGIN_PATH, json={"email": user.email, "password": password}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert settings.SESSION_COOKIE_NAME in client.cookies
    return response


async def create_organisation(
    db: AsyncSession,
    *,
    name: str | None = None,
    short_name: str = "TST",
    country: str = "GR",
    type: OrganisationType = OrganisationType.OTHER,
    is_partner: bool = False,
    sort_order: int = 0,
    website: str | None = None,
) -> Organisation:
    """Insert a (non-partner by default) organisation and flush. Register committed ones with
    the ``cleanup_organisations`` fixture."""
    organisation = Organisation(
        name=name or f"Test Organisation {uuid.uuid4().hex[:12]}",
        short_name=short_name,
        country=country,
        type=type,
        is_partner=is_partner,
        sort_order=sort_order,
        website=website,
    )
    db.add(organisation)
    await db.flush()
    return organisation
