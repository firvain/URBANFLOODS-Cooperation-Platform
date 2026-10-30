"""FastAPI dependencies shared by endpoints.

``DbTx`` gives an endpoint one transaction for the whole request: committed when the endpoint
returns, rolled back if it raises (unless it raises an ``AppError`` with ``keep_changes=True``,
which commits and then propagates). ``scope="function"`` makes the commit happen before the
response is sent, so a client never sees a success for a write that then failed to commit.

Auth: ``get_current_user`` resolves the session cookie (optional user); ``require_user``,
``require_verified``, ``require_admin`` and ``require_superadmin`` build on it. They take the same
``DbTx`` as the endpoint (FastAPI caches a dependency per request by callable and scope), so the
session touch and any revocation happen on the request's single connection and transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import session as crud_session
from app.db.enums import UserRole
from app.db.models import User
from app.db.session import AsyncSessionLocal

CLIENT_IP_HEADER = "CF-Connecting-IP"
# Raw session tokens are 43 characters; anything far longer is not ours and is not looked up.
MAX_SESSION_COOKIE_LENGTH = 256
ADMIN_ROLES = frozenset({UserRole.ADMIN, UserRole.SUPERADMIN})

log = structlog.get_logger(__name__)


async def get_db_tx() -> AsyncIterator[AsyncSession]:
    """Yield a session: commit on success, roll back on exception, except that an ``AppError``
    with ``keep_changes=True`` commits before it propagates."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except AppError as exc:
            if exc.keep_changes:
                await session.commit()
            else:
                await session.rollback()
            raise
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()


DbTx = Annotated[AsyncSession, Depends(get_db_tx, scope="function")]


def client_ip(request: Request) -> str | None:
    """The client's IP: Cloudflare's header behind the proxy, else the socket peer.

    Used only transiently (Turnstile, rate limits). Never stored.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get(CLIENT_IP_HEADER)
        if forwarded:
            return forwarded.strip()
    return request.client.host if request.client else None


# --- auth -------------------------------------------------------------------------------------


async def get_current_user(request: Request, db: DbTx) -> User | None:
    """The signed-in user (with ``organisation`` and ``notification_preferences`` loaded), or
    None. Never raises for a missing or bad cookie.

    A valid session is touched (sliding expiry) and stashed on ``request.state.session``. A
    session whose user is inactive or deleted counts as signed out and is revoked on this
    request's transaction; ``request.state.revoked_disabled_session`` tells ``require_user`` to
    keep that change when it answers 401.
    """
    request.state.session = None
    request.state.revoked_disabled_session = False
    raw = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw or len(raw) > MAX_SESSION_COOKIE_LENGTH:
        return None
    session = await crud_session.get_active_session_by_raw_token(db, raw_token=raw)
    if session is None:
        return None
    if not session.user.is_active or session.user.deleted_at is not None:
        await crud_session.revoke_session(db, session_id=session.id)
        request.state.revoked_disabled_session = True
        log.info("auth.session_of_disabled_user_revoked", user_id=session.user_id)
        return None

    await crud_session.touch_session(db, session=session)
    request.state.session = session
    return session.user


CurrentUser = Annotated[User | None, Depends(get_current_user)]


async def require_user(request: Request, user: CurrentUser) -> User:
    if user is None:
        raise AppError(
            401,
            "auth.not_authenticated",
            "Please sign in.",
            keep_changes=getattr(request.state, "revoked_disabled_session", False),
        )
    return user


AuthUser = Annotated[User, Depends(require_user)]


async def require_verified(user: AuthUser) -> User:
    if not user.is_verified:
        raise AppError(403, "auth.email_not_verified", "Please verify your email address first.")
    return user


VerifiedUser = Annotated[User, Depends(require_verified)]


async def require_admin(user: VerifiedUser) -> User:
    if user.role not in ADMIN_ROLES:
        raise AppError(403, "auth.forbidden", "You do not have permission to do this.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_superadmin(user: AdminUser) -> User:
    if user.role != UserRole.SUPERADMIN:
        raise AppError(403, "auth.forbidden", "You do not have permission to do this.")
    return user


SuperadminUser = Annotated[User, Depends(require_superadmin)]
