"""User data access. Never commits; the caller (``get_db_tx``) does."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import AppError, validation_error
from app.core.security import hash_password, password_needs_rehash, validate_password_policy
from app.crud import expertise as crud_expertise
from app.crud import session as crud_session
from app.crud import token as crud_token
from app.db.enums import ContentType, TokenPurpose, UserRole
from app.db.models import (
    Attachment,
    AuditLog,
    Comment,
    ExpertiseTag,
    KnowbaseLink,
    NotificationPreference,
    Organisation,
    Post,
    Reply,
    Report,
    Session,
    Thread,
    User,
)

EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"
# Fields a user may change on their own profile (``PATCH /auth/me``).
PROFILE_FIELDS = frozenset(
    {
        "display_name",
        "organisation_id",
        "organisation_other",
        "country",
        "locale",
        "bio",
        "show_email",
        "show_in_directory",
        "expertise_ids",
        "expertise_other",
    }
)


async def get_user_by_email(db: AsyncSession, *, email: str) -> User | None:
    """Case-insensitive lookup (``users.email`` is CITEXT). Includes inactive/deleted users."""
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, *, user_id: int) -> User | None:
    """The user with ``organisation``, ``notification_preferences``, ``avatar`` and
    ``expertise`` eagerly loaded."""
    stmt = (
        select(User)
        .options(
            joinedload(User.organisation),
            joinedload(User.notification_preferences),
            joinedload(User.avatar),
            selectinload(User.expertise),
        )
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).unique().scalar_one_or_none()


async def _load_expertise_tags(
    db: AsyncSession, ids: Iterable[int], *, held: Iterable[ExpertiseTag] = ()
) -> list[ExpertiseTag]:
    """The tags for ``ids`` (duplicates collapse), in ``sort_order``. Tags in ``held`` (the
    user's current expertise) are kept even if since deactivated; every other id must be an
    active tag. Raises ``AppError`` 422 (``fields.expertise_ids = "not_found"``) otherwise."""
    wanted = set(ids)
    kept = [tag for tag in held if tag.id in wanted]
    new_ids = wanted - {tag.id for tag in kept}
    added = await crud_expertise.get_active_tags(db, tag_ids=new_ids)
    if len(added) != len(new_ids):
        raise validation_error({"expertise_ids": "not_found"})
    return sorted([*kept, *added], key=lambda tag: (tag.sort_order, tag.id))


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
    expertise_ids: Iterable[int] | None = None,
    expertise_other: str | None = None,
) -> User:
    """Create an unverified member with default notification preferences and the given
    expertise (duplicates collapse) and free-text "other" area of expertise.

    Raises ``PasswordPolicyError`` for a weak password, ``AppError`` 422 (``fields.
    organisation_id = "not_found"``) for an unknown organisation or (``fields.expertise_ids =
    "not_found"``) for an unknown or inactive expertise tag, and ``AppError`` 409
    ``auth.email_taken`` if the address (any case) is already registered.
    """
    validate_password_policy(password)
    if organisation_id is not None and await db.get(Organisation, organisation_id) is None:
        raise validation_error({"organisation_id": "not_found"})
    tags = await _load_expertise_tags(db, expertise_ids or ())

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
        expertise_other=expertise_other,
    )
    user.notification_preferences = NotificationPreference()
    user.expertise = tags
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

    ``expertise_ids`` replaces the user's expertise as a set (``user.expertise`` must be loaded);
    it is reported as ``expertise``. Tags the user already holds may stay even if deactivated
    since. Raises ``AppError`` 422 (``fields.expertise_ids = "not_found"``) if any other id is
    unknown or inactive.
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
    tags = None
    if "expertise_ids" in values:
        tags = await _load_expertise_tags(db, values.pop("expertise_ids"), held=user.expertise)

    changed = sorted(name for name, value in values.items() if getattr(user, name) != value)
    for name in changed:
        setattr(user, name, values[name])
    if tags is not None and {tag.id for tag in tags} != {tag.id for tag in user.expertise}:
        user.expertise = tags
        changed = sorted([*changed, "expertise"])
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
    include_deleted: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[User]]:
    """``(total, users)`` for the admin list, newest first, with ``organisation`` and
    ``expertise`` loaded.
    Soft-deleted users are left out (list and total) unless ``include_deleted``; deletion also
    clears ``is_active``, so ``active=False`` alone means banned accounts. ``q`` is a
    case-insensitive substring of email or display name."""
    conditions = []
    if not include_deleted:
        conditions.append(User.deleted_at.is_(None))
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
        .options(
            joinedload(User.organisation), joinedload(User.avatar), selectinload(User.expertise)
        )
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
        "moderation_decisions",
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


async def disable_notification_preference(
    db: AsyncSession, *, user_id: int, preference: str
) -> bool:
    """Switch one boolean email preference off for ``user_id`` (one-click unsubscribe). Creates
    the preferences row when missing. Returns whether anything changed; an unknown or deleted
    (anonymised) account is a no-op that returns False and creates nothing."""
    if preference not in NOTIFICATION_FIELDS or preference == "digest_frequency":
        raise ValueError(f"Not a switchable email preference: {preference!r}")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return False
    preferences = await get_notification_preferences(db, user=user)
    if not getattr(preferences, preference):
        return False
    setattr(preferences, preference, False)
    await db.flush()
    return True


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
    posts: list[Post]
    threads: list[Thread]
    replies: list[Reply]
    comments: list[Comment]
    attachments: list[Attachment]
    reports: list[Report]
    # ``(content_type, content_id)`` -> the content's KNOWBASE links in display order.
    knowbase_links: dict[tuple[ContentType, int], list[KnowbaseLink]]


async def _all(db: AsyncSession, stmt: Any) -> list[Any]:
    return list((await db.scalars(stmt)).all())


async def export_user_data(db: AsyncSession, *, user: User) -> UserDataExport:
    """The user (``organisation``, ``notification_preferences`` and ``expertise`` loaded), and,
    oldest first: every session of theirs (revoked and expired too); their posts, threads,
    replies and comments in every status (posts and threads with category and tags loaded);
    their uploads (soft-deleted ones too); the reports they made; the KNOWBASE links of their
    posts and threads; and every audit row they made or that is about them or their content
    (posts, threads, replies, comments, uploads, reports).

    One query per kind: a member's own rows are few, so nothing is paginated.
    """
    loaded = await get_user_by_id(db, user_id=user.id)
    assert loaded is not None
    uid = user.id
    posts = await _all(
        db,
        select(Post)
        .where(Post.author_id == uid)
        .options(joinedload(Post.category), selectinload(Post.tags))
        .order_by(Post.created_at, Post.id),
    )
    threads = await _all(
        db,
        select(Thread)
        .where(Thread.author_id == uid)
        .options(joinedload(Thread.category), selectinload(Thread.tags))
        .order_by(Thread.created_at, Thread.id),
    )
    replies = await _all(
        db, select(Reply).where(Reply.author_id == uid).order_by(Reply.created_at, Reply.id)
    )
    comments = await _all(
        db,
        select(Comment).where(Comment.author_id == uid).order_by(Comment.created_at, Comment.id),
    )
    attachments = await _all(
        db,
        select(Attachment)
        .where(Attachment.uploader_id == uid)
        .order_by(Attachment.created_at, Attachment.id),
    )
    reports = await _all(
        db,
        select(Report).where(Report.reporter_id == uid).order_by(Report.created_at, Report.id),
    )

    links: dict[tuple[ContentType, int], list[KnowbaseLink]] = {}
    owned_topics = [
        (ContentType.POST, [post.id for post in posts]),
        (ContentType.THREAD, [thread.id for thread in threads]),
    ]
    link_filters = [
        and_(KnowbaseLink.content_type == kind, KnowbaseLink.content_id.in_(ids))
        for kind, ids in owned_topics
        if ids
    ]
    if link_filters:
        link_stmt = (
            select(KnowbaseLink)
            .where(or_(*link_filters))
            .order_by(KnowbaseLink.sort_order, KnowbaseLink.id)
        )
        for link in await _all(db, link_stmt):
            links.setdefault((link.content_type, link.content_id), []).append(link)

    # Audit rows about the member's content: matched by subquery, so deleted content counts too.
    owned_targets = [
        ("post", select(Post.id).where(Post.author_id == uid)),
        ("thread", select(Thread.id).where(Thread.author_id == uid)),
        ("reply", select(Reply.id).where(Reply.author_id == uid)),
        ("comment", select(Comment.id).where(Comment.author_id == uid)),
        ("attachment", select(Attachment.id).where(Attachment.uploader_id == uid)),
        ("report", select(Report.id).where(Report.reporter_id == uid)),
    ]
    audit_stmt = (
        select(AuditLog)
        .where(
            or_(
                AuditLog.actor_id == uid,
                and_(AuditLog.target_type == "user", AuditLog.target_id == uid),
                *(
                    and_(AuditLog.target_type == kind, AuditLog.target_id.in_(ids))
                    for kind, ids in owned_targets
                ),
            )
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    sessions_stmt = (
        select(Session).where(Session.user_id == uid).order_by(Session.created_at, Session.id)
    )
    return UserDataExport(
        user=loaded,
        sessions=await _all(db, sessions_stmt),
        audit_entries=await _all(db, audit_stmt),
        posts=posts,
        threads=threads,
        replies=replies,
        comments=comments,
        attachments=attachments,
        reports=reports,
        knowbase_links=links,
    )


class AnonymiseResult(NamedTuple):
    """What :func:`anonymise_user` changed besides the user row."""

    sessions_revoked: int
    reports_closed: int
    content_recounted: int


async def anonymise_user(
    db: AsyncSession, *, user: User, now: datetime | None = None
) -> AnonymiseResult:
    """Erase the user's personal data and disable the account (GDPR erasure; the row stays so
    content and audit rows keep a valid reference, shown as "Deleted user").

    Clears every identifying field, frees the email address, blanks the password hash (no
    password verifies against it), demotes to ``member`` and soft-deletes. Revokes every
    session, invalidates every unused email token, deletes the notification preferences and
    the expertise, and hides the account from the members directory. Dismisses the user's open
    reports (a system action, audited as ``report.dismiss`` with ``reason: reporter_deleted``)
    and recounts the reported content, so a deleted reporter no longer counts towards
    ``report_count``. Returns the sessions revoked, reports closed and content recounted.
    Authorisation and auditing the account deletion are the caller's job.
    """
    now = now or datetime.now(UTC)
    # Load the relationships (async: no lazy loading) so the orphan and the junction rows are
    # deleted on flush.
    await db.refresh(user, attribute_names=["notification_preferences", "expertise"])
    user.notification_preferences = None
    user.expertise = []

    user.email = deleted_email(user.id)
    user.display_name = DELETED_DISPLAY_NAME
    user.password_hash = ""
    user.organisation_id = None
    user.organisation_other = None
    user.expertise_other = None
    user.country = None
    user.bio = None
    user.avatar_attachment_id = None
    user.is_active = False
    user.is_verified = False
    user.role = UserRole.MEMBER
    user.trusted_at = None
    user.show_email = False
    user.show_in_directory = False
    user.deleted_at = now
    await db.flush()

    revoked = await crud_session.revoke_all_sessions_for_user(db, user_id=user.id, now=now)
    await crud_token.invalidate_email_tokens(
        db, user_id=user.id, purposes=tuple(TokenPurpose), now=now
    )
    # Imported here: crud.reports -> crud.moderation -> crud.user is circular at load time.
    from app.crud import reports as crud_reports

    closed, recounted = await crud_reports.dismiss_reports_of_deleted_reporter(
        db, reporter_id=user.id, now=now
    )
    return AnonymiseResult(
        sessions_revoked=revoked, reports_closed=closed, content_recounted=recounted
    )
