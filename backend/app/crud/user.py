"""User data access. Never commits; the caller (``get_db_tx``) does."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import AppError, validation_error
from app.core.security import hash_password, password_needs_rehash, validate_password_policy
from app.crud import session as crud_session
from app.crud import token as crud_token
from app.db.enums import TokenPurpose, UserRole
from app.db.models import AuditLog, NotificationPreference, Organisation, Session, User

EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"
# Fields a user may change on their own profile (``PATCH /auth/me``).
PROFILE_FIELDS = frozenset(
    {"display_name", "organisation_id", "organisation_other", "country", "locale", "bio"}
)


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


async def record_login(
    db: AsyncSession, *, user: User, password: str, now: datetime | None = None
) -> None:
    """Bookkeeping after a successful password check: set ``last_login_at`` and, if the stored
    hash uses outdated argon2 parameters, replace it with a fresh one for ``password``."""
    if password_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, password)
    user.last_login_at = now or datetime.now(UTC)
    await db.flush()


async def update_profile(db: AsyncSession, *, user: User, changes: Mapping[str, Any]) -> list[str]:
    """Apply profile ``changes`` (only the keys present; ``None`` clears). Returns the sorted
    names of the fields whose value actually changed.

    Setting ``organisation_id`` clears ``organisation_other`` and vice versa. Raises ``AppError``
    422 (``fields.organisation_id = "not_found"``) for an unknown organisation. Callers reload the
    user (``get_user_by_id``) to see the new ``organisation`` relationship.
    """
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:
        raise ValueError(f"not profile fields: {sorted(unknown)}")
    values = dict(changes)
    if values.get("organisation_id") is not None:
        if await db.get(Organisation, values["organisation_id"]) is None:
            raise validation_error({"organisation_id": "not_found"})
        values["organisation_other"] = None
    if values.get("organisation_other") is not None:
        values["organisation_id"] = None

    changed = sorted(name for name, value in values.items() if getattr(user, name) != value)
    for name in changed:
        setattr(user, name, values[name])
    if changed:
        await db.flush()
    return changed


async def set_password(db: AsyncSession, *, user: User, password: str) -> None:
    """Validate ``password`` against the policy, then store its argon2id hash.

    Raises ``PasswordPolicyError`` (nothing changed) for a weak password. Session revocation and
    token invalidation are the caller's decision.
    """
    validate_password_policy(password)
    # argon2 is deliberately slow; keep it off the event loop.
    user.password_hash = await asyncio.to_thread(hash_password, password)
    await db.flush()


async def set_email(db: AsyncSession, *, user: User, email: str) -> None:
    """Change the user's address. Raises ``AppError`` 409 ``auth.email_taken`` if the address
    (any case; ``users.email`` is CITEXT unique) belongs to another account."""
    try:
        # A savepoint keeps the outer transaction usable if the update fails.
        async with db.begin_nested():
            user.email = email
            await db.flush()
    except IntegrityError as exc:
        if EMAIL_UNIQUE_CONSTRAINT in str(exc.orig):
            raise AppError(
                409, "auth.email_taken", "An account with this email address already exists."
            ) from None
        raise


# --- admin ------------------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    role: UserRole | None = None,
    trusted: bool | None = None,
    verified: bool | None = None,
    active: bool | None = None,
    organisation_id: int | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[User]]:
    """``(total, users)`` for the admin list, newest first, with ``organisation`` loaded.
    Includes soft-deleted users. ``q`` is a case-insensitive substring of email or display
    name."""
    conditions = []
    if q:
        pattern = f"%{_escape_like(q)}%"
        conditions.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        conditions.append(User.role == role)
    if trusted is not None:
        conditions.append(User.trusted_at.is_not(None) if trusted else User.trusted_at.is_(None))
    if verified is not None:
        conditions.append(User.is_verified.is_(verified))
    if active is not None:
        conditions.append(User.is_active.is_(active))
    if organisation_id is not None:
        conditions.append(User.organisation_id == organisation_id)

    total_stmt = select(func.count()).select_from(select(User.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = (
        select(User)
        .options(joinedload(User.organisation))
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return total, list((await db.scalars(stmt)).all())


async def set_role(db: AsyncSession, *, user: User, role: UserRole) -> bool:
    """Set the user's role. Returns True if it changed. Authorisation is the caller's job."""
    if user.role == role:
        return False
    user.role = role
    await db.flush()
    return True


async def set_active(
    db: AsyncSession, *, user: User, active: bool, now: datetime | None = None
) -> bool:
    """Activate or deactivate (ban) the user. Deactivating also revokes every session. Returns
    True if the flag changed."""
    if user.is_active == active:
        return False
    user.is_active = active
    await db.flush()
    if not active:
        await crud_session.revoke_all_sessions_for_user(db, user_id=user.id, now=now)
    return True


async def set_trusted(
    db: AsyncSession, *, user: User, trusted: bool, now: datetime | None = None
) -> bool:
    """Set (keeping an existing timestamp) or clear ``trusted_at``. Returns True if it
    changed."""
    if (user.trusted_at is not None) == trusted:
        return False
    user.trusted_at = (now or datetime.now(UTC)) if trusted else None
    await db.flush()
    return True


async def count_superadmins(db: AsyncSession) -> int:
    """Active, not-deleted superadmins."""
    stmt = select(func.count()).where(
        User.role == UserRole.SUPERADMIN, User.is_active.is_(True), User.deleted_at.is_(None)
    )
    return (await db.execute(stmt)).scalar_one()


# --- notification preferences -----------------------------------------------------------------

NOTIFICATION_FIELDS = frozenset(
    {
        "reply_to_my_thread",
        "comment_on_my_post",
        "reply_to_my_reply",
        "admin_digest",
        "digest_frequency",
    }
)


async def get_notification_preferences(db: AsyncSession, *, user: User) -> NotificationPreference:
    """The user's notification preferences. A missing row (not expected: it is created with the
    user) is created with the defaults."""
    preferences = await db.get(NotificationPreference, user.id)
    if preferences is None:
        preferences = NotificationPreference(user_id=user.id)
        db.add(preferences)
        await db.flush()
        await db.refresh(preferences)
    return preferences


async def update_notification_preferences(
    db: AsyncSession, *, user: User, values: Mapping[str, Any]
) -> tuple[NotificationPreference, list[str]]:
    """Replace the user's preferences with ``values`` (every field). Returns the row and the
    sorted names of the fields whose value actually changed."""
    if set(values) != NOTIFICATION_FIELDS:
        raise ValueError(f"expected exactly the fields {sorted(NOTIFICATION_FIELDS)}")
    preferences = await get_notification_preferences(db, user=user)
    changed = sorted(name for name, value in values.items() if getattr(preferences, name) != value)
    for name in changed:
        setattr(preferences, name, values[name])
    if changed:
        await db.flush()
    return preferences, changed


# --- GDPR: export and anonymisation -----------------------------------------------------------

DELETED_DISPLAY_NAME = "Deleted user"


def deleted_email(user_id: int) -> str:
    """The placeholder address of an anonymised account. ``.invalid`` is reserved (RFC 2606), so
    it can never receive mail, and it frees the real address for a new registration."""
    return f"deleted-{user_id}@invalid"


@dataclass(frozen=True, slots=True)
class UserDataExport:
    """Everything stored about one user, for ``GET /auth/me/export``."""

    user: User
    sessions: list[Session]
    audit_entries: list[AuditLog]


async def export_user_data(db: AsyncSession, *, user: User) -> UserDataExport:
    """The user (``organisation`` and ``notification_preferences`` loaded), every session of
    theirs (revoked and expired too), oldest first, and every audit row they made or that is
    about them, oldest first.

    Content (posts, threads, replies, comments) joins the export when it exists (M2/M3).
    """
    loaded = await get_user_by_id(db, user_id=user.id)
    assert loaded is not None
    sessions_stmt = (
        select(Session).where(Session.user_id == user.id).order_by(Session.created_at, Session.id)
    )
    audit_stmt = (
        select(AuditLog)
        .where(
            or_(
                AuditLog.actor_id == user.id,
                and_(AuditLog.target_type == "user", AuditLog.target_id == user.id),
            )
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    return UserDataExport(
        user=loaded,
        sessions=list((await db.scalars(sessions_stmt)).all()),
        audit_entries=list((await db.scalars(audit_stmt)).all()),
    )


async def anonymise_user(db: AsyncSession, *, user: User, now: datetime | None = None) -> int:
    """Erase the user's personal data and disable the account (GDPR erasure; the row stays so
    content and audit rows keep a valid reference, shown as "Deleted user").

    Clears every identifying field, frees the email address, blanks the password hash (no
    password verifies against it), demotes to ``member`` and soft-deletes. Revokes every
    session, invalidates every unused email token and deletes the notification preferences.
    Returns the number of sessions revoked. Authorisation and auditing are the caller's job.
    """
    now = now or datetime.now(UTC)
    # Load the relationship (async: no lazy loading) so the orphan is deleted on flush.
    await db.refresh(user, attribute_names=["notification_preferences"])
    user.notification_preferences = None

    user.email = deleted_email(user.id)
    user.display_name = DELETED_DISPLAY_NAME
    user.password_hash = ""
    user.organisation_id = None
    user.organisation_other = None
    user.country = None
    user.bio = None
    user.avatar_attachment_id = None
    user.is_active = False
    user.is_verified = False
    user.role = UserRole.MEMBER
    user.trusted_at = None
    user.deleted_at = now
    await db.flush()

    revoked = await crud_session.revoke_all_sessions_for_user(db, user_id=user.id, now=now)
    await crud_token.invalidate_email_tokens(
        db, user_id=user.id, purposes=tuple(TokenPurpose), now=now
    )
    return revoked
