"""Single-use email tokens (verify email, reset password, change email).

Only the SHA-256 hash of a token is stored. Consumption is one atomic
``UPDATE ... WHERE used_at IS NULL ... RETURNING``, so a token cannot be used twice even under
concurrent requests. Never commits; the caller does.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token, token_expiry
from app.db.enums import TokenPurpose
from app.db.models import EmailToken


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def create_email_token(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: TokenPurpose,
    new_email: str | None = None,
    now: datetime | None = None,
) -> tuple[EmailToken, str]:
    """Issue a token; returns ``(token, raw_token)``.

    Any older unused token of the same purpose for the user is invalidated first
    (``used_at = now``), so only the most recent link works.
    """
    now = _now(now)
    await db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token, token_hash = generate_token()
    token = EmailToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=token_hash,
        new_email=new_email,
        created_at=now,
        expires_at=token_expiry(purpose, now),
    )
    db.add(token)
    await db.flush()
    return token, raw_token


async def consume_email_token(
    db: AsyncSession, *, raw_token: str, purpose: TokenPurpose, now: datetime | None = None
) -> EmailToken | None:
    """Mark the token used and return it, or None if unknown, used, expired or wrong purpose."""
    now = _now(now)
    stmt = (
        update(EmailToken)
        .where(
            EmailToken.token_hash == hash_token(raw_token),
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(EmailToken)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def invalidate_email_tokens(
    db: AsyncSession,
    *,
    user_id: int,
    purposes: Iterable[TokenPurpose],
    now: datetime | None = None,
) -> int:
    """Mark every unused token of the user with one of ``purposes`` as used (``used_at = now``),
    so links already sent stop working. Returns how many were invalidated."""
    stmt = (
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose.in_(list(purposes)),
            EmailToken.used_at.is_(None),
        )
        .values(used_at=_now(now))
        .returning(EmailToken.id)
    )
    return len((await db.execute(stmt)).all())


async def delete_expired_tokens(
    db: AsyncSession, *, now: datetime | None = None, older_than_days: int = 7
) -> int:
    """Hard-delete tokens that expired or were used more than ``older_than_days`` ago."""
    cutoff = _now(now) - timedelta(days=older_than_days)
    stmt = (
        delete(EmailToken)
        .where(or_(EmailToken.expires_at < cutoff, EmailToken.used_at < cutoff))
        .returning(EmailToken.id)
    )
    return len((await db.execute(stmt)).all())
