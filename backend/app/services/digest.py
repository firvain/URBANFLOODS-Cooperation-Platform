"""The daily admin moderation digest.

:func:`build_admin_digest` collects what moderators should look at: the pending posts and threads
and the open reports (current state, not windowed), plus the new members and the content
published since the previous run (windowed). The window runs from the previous
``admin_daily`` run's ``window_end`` (or 24 hours back when there is none) to ``now``.

:func:`send_admin_digest` emails it to every active, verified admin/superadmin whose
``admin_digest`` preference is on (``weekly`` recipients only on Mondays) in their own locale
(English fallback), and records a :class:`DigestRun` so the next window starts where this one
ended. Weekly recipients get their own build of the digest covering the last 7 days. When there
is nothing to review (no pending items, no open reports) and ``force`` is off, nothing is sent
but the run is still recorded. One failed recipient never stops the others; when every send
fails, no run is recorded, so the same window is retried next time. Addresses are never logged.
Never commits; the caller does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import digest as crud_digest
from app.crud import moderation as crud_moderation
from app.crud import reports as crud_reports
from app.db.enums import DigestFrequency
from app.db.models import DigestRun, User
from app.services import email as email_service

ADMIN_DIGEST_KIND = "admin_daily"
TEMPLATE = "admin_digest"
DEFAULT_WINDOW = timedelta(hours=24)
WEEKLY_WINDOW = timedelta(days=7)
PENDING_LIMIT = 50
REPORTS_LIMIT = 10

# Frontend paths (templates prefix them with ``frontend_url``).
QUEUE_PATH = "/admin/queue"
REPORTS_PATH = "/admin/reports"
SETTINGS_PATH = "/account?tab=notifications"
WEEKLY_DAY = 0  # Monday

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PendingItem:
    content_type: str
    content_id: int
    title: str
    author_name: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReportItem:
    report_id: int
    content_type: str
    content_id: int
    reason: str
    created_at: datetime


@dataclass(frozen=True)
class DigestData:
    window_start: datetime
    window_end: datetime
    pending_total: int
    pending: list[PendingItem]
    reports_total: int
    reports: list[ReportItem]
    new_members: int
    published: dict[str, int] = field(default_factory=dict)

    @property
    def items(self) -> int:
        """What needs a moderator: pending posts/threads plus open reports."""
        return self.pending_total + self.reports_total


async def build_admin_digest(
    db: AsyncSession, *, now: datetime, since: datetime | None = None
) -> DigestData:
    """The digest for ``[since, now)``; without ``since`` the window starts at the previous
    ``admin_daily`` run's end (or 24 hours back)."""
    if since is not None:
        start = since
    else:
        last = await crud_digest.get_last_run(db, kind=ADMIN_DIGEST_KIND)
        start = last.window_end if last is not None else now - DEFAULT_WINDOW
    pending_total, pending = await crud_moderation.list_pending(db, limit=PENDING_LIMIT)
    reports = await crud_digest.list_newest_open_reports(db, limit=REPORTS_LIMIT)
    return DigestData(
        window_start=start,
        window_end=now,
        pending_total=pending_total,
        pending=[
            PendingItem(
                content_type=content_type.value,
                content_id=obj.id,
                title=obj.title,
                author_name=obj.author.display_name if obj.author is not None else None,
                created_at=obj.created_at,
            )
            for content_type, obj in pending
        ],
        reports_total=await crud_reports.count_open(db),
        reports=[
            ReportItem(
                report_id=report.id,
                content_type=report.content_type.value,
                content_id=report.content_id,
                reason=report.reason.value,
                created_at=report.created_at,
            )
            for report in reports
        ],
        new_members=await crud_digest.count_new_members(db, start=start, end=now),
        published=await crud_digest.count_published(db, start=start, end=now),
    )


def _fmt(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _context(data: DigestData, recipient: User) -> dict[str, Any]:
    return {
        "display_name": recipient.display_name,
        "window_start": _fmt(data.window_start),
        "window_end": _fmt(data.window_end),
        "pending_total": data.pending_total,
        "pending": [
            {
                "content_type": item.content_type,
                "content_id": item.content_id,
                "title": item.title,
                "author_name": item.author_name or "(removed account)",
                "created_at": _fmt(item.created_at),
            }
            for item in data.pending
        ],
        "pending_more": max(data.pending_total - len(data.pending), 0),
        "reports_total": data.reports_total,
        "reports": [
            {
                "content_type": item.content_type,
                "content_id": item.content_id,
                "reason": item.reason,
                "created_at": _fmt(item.created_at),
            }
            for item in data.reports
        ],
        "reports_more": max(data.reports_total - len(data.reports), 0),
        "new_members": data.new_members,
        "published": data.published,
        "queue_url": QUEUE_PATH,
        "reports_url": REPORTS_PATH,
        "settings_url": SETTINGS_PATH,
    }


async def send_admin_digest(
    db: AsyncSession, *, now: datetime | None = None, force: bool = False
) -> DigestRun | None:
    """Build, send and record one admin digest run (see the module docstring). Returns the
    recorded run, or ``None`` when every send failed (nothing recorded)."""
    now = now or datetime.now(UTC)
    daily = await build_admin_digest(db, now=now)
    attempted = sent = 0
    if daily.items > 0 or force:
        weekly_due = now.astimezone(UTC).weekday() == WEEKLY_DAY
        recipients = await crud_digest.list_admin_digest_recipients(db, weekly_due=weekly_due)
        weekly: DigestData | None = None
        if any(freq == DigestFrequency.WEEKLY for _, freq in recipients):
            weekly = await build_admin_digest(db, now=now, since=now - WEEKLY_WINDOW)
        for recipient, frequency in recipients:
            data = weekly if frequency == DigestFrequency.WEEKLY and weekly else daily
            attempted += 1
            try:
                await email_service.send_email(
                    to=recipient.email,
                    template=TEMPLATE,
                    locale=recipient.locale,
                    context=_context(data, recipient),
                )
            except Exception as exc:
                # Error type only: the message could carry the address.
                log.error("digest.failed", recipient_id=recipient.id, error=type(exc).__name__)
                continue
            sent += 1
    if attempted and not sent:
        log.error(
            "digest.failed_all", kind=ADMIN_DIGEST_KIND, recipients=attempted, items=daily.items
        )
        return None
    run = await crud_digest.create_run(
        db,
        kind=ADMIN_DIGEST_KIND,
        ran_at=now,
        window_start=daily.window_start,
        window_end=daily.window_end,
        recipients=sent,
        items=daily.items,
    )
    log.info(
        "digest.sent",
        kind=ADMIN_DIGEST_KIND,
        recipients=sent,
        items=daily.items,
        forced=force,
    )
    return run
