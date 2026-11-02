"""Data access for the scheduled jobs: digest runs, digest contents and recipients, and the
maintenance purges. Never commits; the caller (``services/scheduler.py``) does.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.attachment import unused_attachment_conditions
from app.db.enums import ContentStatus, DigestFrequency, ReportStatus, UserRole
from app.db.models import (
    Attachment,
    Comment,
    DigestRun,
    NotificationPreference,
    Post,
    Reply,
    Report,
    Thread,
    User,
)

# --- digest runs ------------------------------------------------------------------------------


async def get_last_run(db: AsyncSession, *, kind: str) -> DigestRun | None:
    """The run of ``kind`` with the latest ``window_end``."""
    stmt = (
        select(DigestRun)
        .where(DigestRun.kind == kind)
        .order_by(DigestRun.window_end.desc(), DigestRun.id.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def create_run(
    db: AsyncSession,
    *,
    kind: str,
    ran_at: datetime,
    window_start: datetime,
    window_end: datetime,
    recipients: int,
    items: int,
) -> DigestRun:
    run = DigestRun(
        kind=kind,
        ran_at=ran_at,
        window_start=window_start,
        window_end=window_end,
        recipients=recipients,
        items=items,
    )
    db.add(run)
    await db.flush()
    return run


# --- digest contents --------------------------------------------------------------------------


async def list_newest_open_reports(db: AsyncSession, *, limit: int = 10) -> list[Report]:
    stmt = (
        select(Report)
        .where(Report.status == ReportStatus.OPEN)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def count_new_members(db: AsyncSession, *, start: datetime, end: datetime) -> int:
    """Accounts created in ``[start, end)`` that still exist (not anonymised)."""
    stmt = select(func.count(User.id)).where(
        User.created_at >= start, User.created_at < end, User.deleted_at.is_(None)
    )
    return (await db.execute(stmt)).scalar_one()


async def count_published(db: AsyncSession, *, start: datetime, end: datetime) -> dict[str, int]:
    """Published content in ``[start, end)``: posts and threads by ``published_at``, replies and
    comments (which are published on creation) by ``created_at``; only rows still published."""
    published = ContentStatus.PUBLISHED

    def _count(model: type, column) -> Select:
        return select(func.count(model.id)).where(
            model.status == published, column >= start, column < end
        )

    stmt = select(
        _count(Post, Post.published_at).scalar_subquery().label("posts"),
        _count(Thread, Thread.published_at).scalar_subquery().label("threads"),
        _count(Reply, Reply.created_at).scalar_subquery().label("replies"),
        _count(Comment, Comment.created_at).scalar_subquery().label("comments"),
    )
    row = (await db.execute(stmt)).one()
    return dict(row._mapping)


async def list_admin_digest_recipients(
    db: AsyncSession, *, weekly_due: bool
) -> list[tuple[User, DigestFrequency]]:
    """``(user, frequency)`` of the active, verified, not anonymised admins and superadmins who
    want the admin digest now: ``admin_digest`` on and ``digest_frequency`` daily (weekly only
    when ``weekly_due``). A missing preferences row counts as the defaults (on, daily)."""
    frequencies = [DigestFrequency.DAILY]
    if weekly_due:
        frequencies.append(DigestFrequency.WEEKLY)
    stmt = (
        select(User, NotificationPreference.digest_frequency)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
        .where(
            User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]),
            User.is_active.is_(True),
            User.is_verified.is_(True),
            User.deleted_at.is_(None),
            or_(
                NotificationPreference.user_id.is_(None),
                and_(
                    NotificationPreference.admin_digest.is_(True),
                    NotificationPreference.digest_frequency.in_(frequencies),
                ),
            ),
        )
        .order_by(User.id)
    )
    return [
        (user, frequency or DigestFrequency.DAILY) for user, frequency in (await db.execute(stmt))
    ]


# --- maintenance ------------------------------------------------------------------------------


async def purge_unverified_users(db: AsyncSession, *, cutoff: datetime) -> int:
    """Hard-delete members who never verified their address and registered before ``cutoff``
    (anonymised accounts excluded). Sessions, email tokens, notification preferences and
    expertise links go with them (``ON DELETE CASCADE``); their uploads, reports and audit rows
    keep a NULL user (``ON DELETE SET NULL``). Returns how many were deleted."""
    stmt = (
        delete(User)
        .where(
            User.is_verified.is_(False),
            User.role == UserRole.MEMBER,
            User.deleted_at.is_(None),
            User.created_at < cutoff,
        )
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    return len((await db.execute(stmt)).all())


async def delete_orphan_attachments(
    db: AsyncSession, *, cutoff: datetime
) -> list[tuple[str, str | None]]:
    """Hard-delete attachments created before ``cutoff`` that nothing uses: not a post cover,
    not an avatar, and not embedded (an ``<img>`` src) in the body of any post, thread, reply or
    comment (whatever its status: deleted content can be restored). Soft-deleted rows qualify too.
    Returns the ``(storage_path, thumb_path)`` of each deleted row; the caller removes files."""
    stmt = (
        delete(Attachment)
        .where(
            Attachment.created_at < cutoff,
            *unused_attachment_conditions(),
        )
        .returning(Attachment.storage_path, Attachment.thumb_path)
        .execution_options(synchronize_session=False)
    )
    return [(row.storage_path, row.thumb_path) for row in (await db.execute(stmt)).all()]
