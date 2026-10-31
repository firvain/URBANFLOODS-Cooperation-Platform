"""Reports: members flag published content; admins resolve or dismiss. Never commits.

A content item's ``report_count`` is the number of distinct reporters with an open report on it
(anonymised reporters, ``reporter_id`` NULL, never count). Creating a report recounts it and then
asks :func:`app.crud.moderation.auto_hide_if_reported` whether the threshold is reached; closing
a report recounts it again (when the content still exists).

Locking: both creating and closing lock the content row first (and closing then the report row),
the same order as ``moderation.unhide``/``restore`` (content row, then its reports), so these
never deadlock each other; concurrent reports on one item are counted one after the other.

Audit rows: ``report.create`` (``{content_type, content_id, reason}``, never the free-text
details), ``report.resolve`` and ``report.dismiss`` (``{content_type, content_id}``), all with
``target_type="report"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import AppError
from app.crud import moderation
from app.crud.audit import log_action
from app.db.enums import ContentStatus, ContentType, ReportReason, ReportStatus
from app.db.models import Comment, Reply, Report, User

ContentModel = moderation.ContentModel
UNIQUE_CONSTRAINT = "uq_reports_reporter_content"


def _content_not_found() -> AppError:
    return AppError(404, "report.content_not_found", "Content not found.")


def _already_reported() -> AppError:
    return AppError(409, "report.already_reported", "You have already reported this.")


def _is_duplicate_violation(exc: IntegrityError) -> bool:
    return UNIQUE_CONSTRAINT in str(exc.orig)


async def _recount(db: AsyncSession, *, content: ContentModel) -> int:
    """Set ``report_count`` to the distinct open reporters (the same count the auto-hide
    threshold is compared with) and return it."""
    count = await moderation.open_reporter_count(
        db, content_type=moderation.content_type_of(content), content_id=content.id
    )
    content.report_count = count
    await db.flush()
    return count


# --- create -----------------------------------------------------------------------------------


async def create_report(
    db: AsyncSession,
    *,
    reporter: User,
    content_type: ContentType,
    content_id: int,
    reason: ReportReason,
    details: str | None,
    now: datetime | None = None,
) -> tuple[Report, bool]:
    """Report published content. Returns ``(report, auto_hidden)``.

    :raises AppError: 404 ``report.content_not_found`` (missing or not published), 400
        ``report.own_content``, 409 ``report.already_reported`` (one report per reporter per
        item, whatever its status).
    """
    content = await moderation.get_content(
        db, content_type=content_type, content_id=content_id, for_update=True
    )
    if content is None or content.status != ContentStatus.PUBLISHED:
        raise _content_not_found()
    if content.author_id == reporter.id:
        raise AppError(400, "report.own_content", "You cannot report your own content.")

    existing = await db.scalar(
        select(Report.id).where(
            Report.reporter_id == reporter.id,
            Report.content_type == content_type,
            Report.content_id == content_id,
        )
    )
    if existing is not None:
        raise _already_reported()

    report = Report(
        reporter_id=reporter.id,
        content_type=content_type,
        content_id=content_id,
        reason=reason,
        details=details,
    )
    try:
        # The unique constraint is the backstop for a race the pre-check missed.
        async with db.begin_nested():
            db.add(report)
            await db.flush()
    except IntegrityError as exc:
        if _is_duplicate_violation(exc):
            raise _already_reported() from exc
        raise
    await db.refresh(report)

    reporters = await _recount(db, content=content)
    auto_hidden = await moderation.auto_hide_if_reported(
        db, content=content, now=now, reporters=reporters
    )
    await log_action(
        db,
        actor_id=reporter.id,
        action="report.create",
        target_type="report",
        target_id=report.id,
        metadata={
            "content_type": content_type.value,
            "content_id": content_id,
            "reason": reason.value,
        },
    )
    return report, auto_hidden


# --- reads ------------------------------------------------------------------------------------


def _with_users(stmt: Any) -> Any:
    return stmt.options(joinedload(Report.reporter), joinedload(Report.resolver))


async def list_reports(
    db: AsyncSession,
    *,
    status: ReportStatus | None = None,
    content_type: ContentType | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[Report]]:
    """``(total, reports)`` newest first, reporter and resolver loaded."""
    conditions = []
    if status is not None:
        conditions.append(Report.status == status)
    if content_type is not None:
        conditions.append(Report.content_type == content_type)
    total_stmt = select(func.count()).select_from(select(Report.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = _with_users(
        select(Report)
        .where(*conditions)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = await db.scalars(stmt)
    return total, list(rows.unique().all())


async def get_report(
    db: AsyncSession, *, report_id: int, for_update: bool = False
) -> Report | None:
    """The report with reporter and resolver loaded, refreshed from the database.

    ``for_update`` locks the report row (not the outer-joined users) until the transaction ends,
    so two admins closing it at once cannot both succeed.
    """
    stmt = _with_users(select(Report).where(Report.id == report_id)).execution_options(
        populate_existing=True
    )
    if for_update:
        stmt = stmt.with_for_update(of=Report)
    return (await db.scalars(stmt)).unique().one_or_none()


async def count_open(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Report).where(Report.status == ReportStatus.OPEN)
    return (await db.execute(stmt)).scalar_one()


async def load_contents(
    db: AsyncSession, *, reports: Sequence[Report]
) -> dict[tuple[ContentType, int], ContentModel]:
    """The reported content (any status) of ``reports``, keyed by ``(content_type, id)``: one
    query per content type present. Replies come with their thread, comments with their post.
    Content that no longer exists is simply absent."""
    wanted: dict[ContentType, set[int]] = {}
    for report in reports:
        wanted.setdefault(report.content_type, set()).add(report.content_id)
    loaded: dict[tuple[ContentType, int], ContentModel] = {}
    for content_type, ids in wanted.items():
        model = moderation.MODELS[content_type]
        stmt = select(model).where(model.id.in_(ids))
        if model is Reply:
            stmt = stmt.options(joinedload(Reply.thread))
        elif model is Comment:
            stmt = stmt.options(joinedload(Comment.post))
        for obj in (await db.scalars(stmt)).unique():
            loaded[(content_type, obj.id)] = obj
    return loaded


# --- resolve / dismiss ------------------------------------------------------------------------


async def _close(
    db: AsyncSession,
    *,
    report: Report,
    actor: User,
    status: ReportStatus,
    action: str,
    now: datetime | None,
) -> Report:
    """Close ``report`` (loaded without a lock). Locks the content row first (absent if the
    content is gone), then re-reads the report under a lock and checks it is still open."""
    content = await moderation.get_content(
        db, content_type=report.content_type, content_id=report.content_id, for_update=True
    )
    locked = await get_report(db, report_id=report.id, for_update=True)
    if locked is None:
        raise AppError(404, "report.not_found", "Report not found.")
    report = locked
    if report.status != ReportStatus.OPEN:
        raise AppError(409, "report.not_open", "This report has already been handled.")
    report.status = status
    report.resolved_by = actor.id
    report.resolved_at = now or datetime.now(UTC)
    await db.flush()
    if content is not None:
        await _recount(db, content=content)
    await log_action(
        db,
        actor_id=actor.id,
        action=action,
        target_type="report",
        target_id=report.id,
        metadata={"content_type": report.content_type.value, "content_id": report.content_id},
    )
    return report


async def resolve_report(
    db: AsyncSession, *, report: Report, actor: User, now: datetime | None = None
) -> Report:
    """``open`` → ``resolved``. 409 ``report.not_open`` otherwise."""
    return await _close(
        db,
        report=report,
        actor=actor,
        status=ReportStatus.RESOLVED,
        action="report.resolve",
        now=now,
    )


async def dismiss_report(
    db: AsyncSession, *, report: Report, actor: User, now: datetime | None = None
) -> Report:
    """``open`` → ``dismissed``. 409 ``report.not_open`` otherwise."""
    return await _close(
        db,
        report=report,
        actor=actor,
        status=ReportStatus.DISMISSED,
        action="report.dismiss",
        now=now,
    )
