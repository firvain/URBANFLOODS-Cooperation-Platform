"""Admin read models: the dashboard overview and the reporting export
(``/admin/stats/export.csv``, used for the project's progress reports and the RCO87 indicator).

Read-only. "Registered users" means accounts not soft-deleted. In the export, a *contribution*
is a published post, thread, reply or comment created in the range (the rows the ``content``
section counts; the same definition as the digest). A sign-in is an ``auth.login`` audit row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, false, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContentStatus, ReportStatus, UserRole
from app.db.models import AuditLog, Comment, Organisation, Post, Reply, Report, Thread, User

NEW_USER_DAYS = 30
OTHER_ORGANISATION = "Other"
NO_ORGANISATION = "Unspecified"
LOGIN_ACTION = "auth.login"

_ADMIN_ROLES = (UserRole.ADMIN, UserRole.SUPERADMIN)


def _count(stmt: Any) -> Any:
    return stmt.scalar_subquery()


# --- overview ---------------------------------------------------------------------------------


async def overview(db: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """User, content and open-report counts for the admin dashboard (two queries).

    ``total`` and ``new_30d`` count every non-deleted account; ``verified``, ``trusted`` and
    ``admins`` only active (not banned) ones.
    """
    now = now or datetime.now(UTC)
    alive = User.deleted_at.is_(None)
    active = User.is_active
    users = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(active & User.is_verified).label("verified"),
                func.count().filter(active & User.trusted_at.is_not(None)).label("trusted"),
                func.count().filter(active & User.role.in_(_ADMIN_ROLES)).label("admins"),
                func.count()
                .filter(User.created_at >= now - timedelta(days=NEW_USER_DAYS))
                .label("new_30d"),
            ).where(alive)
        )
    ).one()

    published = ContentStatus.PUBLISHED
    pending = ContentStatus.PENDING
    content = (
        await db.execute(
            select(
                _count(select(func.count()).where(Post.status == published)).label(
                    "posts_published"
                ),
                _count(select(func.count()).where(Thread.status == published)).label(
                    "threads_published"
                ),
                _count(select(func.count()).where(Reply.status == published)).label("replies"),
                _count(select(func.count()).where(Comment.status == published)).label("comments"),
                (
                    _count(select(func.count()).where(Post.status == pending))
                    + _count(select(func.count()).where(Thread.status == pending))
                ).label("pending"),
                _count(select(func.count()).where(Report.status == ReportStatus.OPEN)).label(
                    "reports_open"
                ),
            )
        )
    ).one()

    return {
        "users": dict(users._mapping),
        "content": {
            key: content._mapping[key]
            for key in ("posts_published", "threads_published", "replies", "comments", "pending")
        },
        "reports_open": content.reports_open,
    }


# --- export -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExportStats:
    users_by_country: list[tuple[str | None, int]]
    users_by_organisation: list[tuple[str, bool, int]]
    content: dict[str, int]
    contributors: int
    logged_in: int
    # (organisation, is_partner, country, contributions)
    rco87: list[tuple[str, bool, str | None, int]]


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """``[start 00:00 UTC, the day after end 00:00 UTC)``: both days inclusive."""
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
    )


async def export_stats(db: AsyncSession, *, start: date, end: date) -> ExportStats:
    """Everything ``/admin/stats/export.csv`` reports for the days ``start``..``end``."""
    lower, upper = day_bounds(start, end)

    def in_range(column: Any) -> Any:
        return (column >= lower) & (column < upper)

    registered = (in_range(User.created_at), User.deleted_at.is_(None))
    user_count = func.count(User.id)

    by_country = (
        await db.execute(
            select(User.country, user_count)
            .where(*registered)
            .group_by(User.country)
            .order_by(user_count.desc(), User.country.asc().nulls_last())
        )
    ).all()

    by_organisation: list[tuple[str, bool, int]] = [
        (row.name, row.is_partner, row.count)
        for row in (
            await db.execute(
                select(Organisation.name, Organisation.is_partner, user_count.label("count"))
                .join(User, User.organisation_id == Organisation.id)
                .where(*registered)
                .group_by(Organisation.id)
                .order_by(user_count.desc(), Organisation.name)
            )
        ).all()
    ]
    unlisted = User.organisation_id.is_(None)
    other, unspecified = (
        await db.execute(
            select(
                func.count().filter(unlisted & User.organisation_other.is_not(None)),
                func.count().filter(unlisted & User.organisation_other.is_(None)),
            ).where(*registered)
        )
    ).one()
    if other:
        by_organisation.append((OTHER_ORGANISATION, False, other))
    if unspecified:
        by_organisation.append((NO_ORGANISATION, False, unspecified))

    published = ContentStatus.PUBLISHED
    sources = {
        "posts": (Post, (in_range(Post.created_at), Post.status == published)),
        "threads": (Thread, (in_range(Thread.created_at), Thread.status == published)),
        "replies": (Reply, (in_range(Reply.created_at), Reply.status == published)),
        "comments": (Comment, (in_range(Comment.created_at), Comment.status == published)),
    }
    counts = (
        await db.execute(
            select(
                *(
                    _count(select(func.count()).select_from(model).where(*conditions)).label(name)
                    for name, (model, conditions) in sources.items()
                )
            )
        )
    ).one()

    contributions = union_all(
        *(
            select(model.author_id.label("author_id")).where(
                *conditions, model.author_id.is_not(None)
            )
            for model, conditions in sources.values()
        )
    ).subquery()
    contributors = (
        await db.execute(select(func.count(func.distinct(contributions.c.author_id))))
    ).scalar_one()
    # ``users.last_login_at`` only keeps the latest sign-in, so count the audit trail.
    logged_in = (
        await db.execute(
            select(func.count(func.distinct(AuditLog.actor_id)))
            .join(User, User.id == AuditLog.actor_id)
            .where(
                AuditLog.action == LOGIN_ACTION,
                in_range(AuditLog.created_at),
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # RCO87: listed organisations, and free-text ones (trimmed, with the member's country) as
    # their own rows; contributors with no organisation at all have no row.
    free_text = func.btrim(User.organisation_other)
    listed = User.organisation_id.is_not(None)
    organisation = case((listed, Organisation.name), else_=free_text)
    is_partner = case((listed, Organisation.is_partner), else_=false())
    country = case((listed, Organisation.country), else_=User.country)
    contribution_count = func.count()
    rco87 = (
        await db.execute(
            select(organisation, is_partner, country, contribution_count)
            .select_from(contributions)
            .join(User, User.id == contributions.c.author_id)
            .outerjoin(Organisation, Organisation.id == User.organisation_id)
            .where(listed | (func.coalesce(free_text, "") != ""))
            .group_by(Organisation.id, organisation, is_partner, country)
            .order_by(contribution_count.desc(), organisation)
        )
    ).all()

    return ExportStats(
        users_by_country=[(row[0], row[1]) for row in by_country],
        users_by_organisation=by_organisation,
        content=dict(counts._mapping),
        contributors=contributors,
        logged_in=logged_in,
        rco87=[(row[0], row[1], row[2], row[3]) for row in rco87],
    )
