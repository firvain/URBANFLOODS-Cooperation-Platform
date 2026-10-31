"""Scheduled jobs: the daily admin digest and the daily maintenance sweeps.

:func:`create_scheduler` builds an APScheduler 3 ``AsyncIOScheduler`` (UTC) with two cron jobs:
``admin_digest`` at ``DIGEST_HOUR_UTC:00`` and ``maintenance`` an hour earlier (wrapping to 23:00
when the digest runs at midnight). The app lifespan starts it only when ``ENABLE_SCHEDULER`` is
set; run a single worker process when it is on, or each worker would send its own digest.

:func:`run_digest` and :func:`run_maintenance` are plain coroutines shared by the jobs and the
CLI (``python -m app.cli digest|maintenance``). Each maintenance step runs in its own session and
transaction, so one failing step neither rolls back nor stops the others; a failed step is logged
(error type only) and reported as ``-1``.

Maintenance steps:

- ``sessions`` / ``tokens``: expired or used/revoked rows older than a week.
- ``unverified_users``: members who never verified and registered more than
  ``UNVERIFIED_PURGE_DAYS`` days ago are hard-deleted (their sessions, tokens and preferences
  cascade); audit ``maintenance.purge_unverified`` with the count only.
- ``orphan_uploads``: attachments older than ``ORPHAN_UPLOAD_HOURS`` hours that are no cover, no
  avatar and not referenced in any body are hard-deleted, their files once the deletion has
  committed; audit ``maintenance.orphan_uploads`` with the count.
- ``auto_approved``: pending posts/threads older than ``AUTO_APPROVE_AFTER_DAYS`` days are
  approved; skipped (0) when the setting is 0.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import digest as crud_digest
from app.crud import moderation as crud_moderation
from app.crud.audit import log_action
from app.crud.session import delete_expired_sessions
from app.crud.token import delete_expired_tokens
from app.db.models import DigestRun
from app.db.session import AsyncSessionLocal
from app.services import images
from app.services.digest import send_admin_digest

TIMEZONE = "UTC"
MISFIRE_GRACE_SECONDS = 3600
FAILED = -1

SessionFactory = Callable[[], AsyncSession]
Step = Callable[..., Awaitable[int]]

log = structlog.get_logger(__name__)


# --- maintenance steps ------------------------------------------------------------------------


async def purge_unverified_users(db: AsyncSession, *, now: datetime) -> int:
    """Hard-delete stale unverified members (see the module docstring). Returns the count."""
    cutoff = now - timedelta(days=settings.UNVERIFIED_PURGE_DAYS)
    count = await crud_digest.purge_unverified_users(db, cutoff=cutoff)
    if count:
        # The count only: no ids or addresses of accounts that no longer exist.
        await log_action(
            db, actor_id=None, action="maintenance.purge_unverified", metadata={"count": count}
        )
    return count


async def sweep_orphan_uploads(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    """Delete the rows of unused old attachments (see the module docstring) and append their
    file paths (relative to ``UPLOAD_DIR``) to ``files``. The caller removes the files only after
    the transaction has committed, so a rollback never leaves rows without files."""
    cutoff = now - timedelta(hours=settings.ORPHAN_UPLOAD_HOURS)
    deleted = await crud_digest.delete_orphan_attachments(db, cutoff=cutoff)
    if deleted:
        await log_action(
            db,
            actor_id=None,
            action="maintenance.orphan_uploads",
            metadata={"count": len(deleted)},
        )
        files.extend(path for pair in deleted for path in pair if path)
    return len(deleted)


async def _expired_sessions(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    return await delete_expired_sessions(db, now=now)


async def _expired_tokens(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    return await delete_expired_tokens(db, now=now)


async def _unverified_users(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    return await purge_unverified_users(db, now=now)


async def _orphan_uploads(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    return await sweep_orphan_uploads(db, now=now, files=files)


async def _auto_approve(db: AsyncSession, *, now: datetime, files: list[str]) -> int:
    return await crud_moderation.auto_approve_stale(db, now=now)


MAINTENANCE_STEPS = ("sessions", "tokens", "unverified_users", "orphan_uploads", "auto_approved")


def _steps() -> dict[str, Step]:
    return {
        "sessions": _expired_sessions,
        "tokens": _expired_tokens,
        "unverified_users": _unverified_users,
        "orphan_uploads": _orphan_uploads,
        "auto_approved": _auto_approve,
    }


# --- entry points (jobs and CLI) --------------------------------------------------------------


async def run_maintenance(
    now: datetime | None = None, *, session_factory: SessionFactory | None = None
) -> dict[str, int]:
    """Run every maintenance step once, each in its own committed transaction. Returns
    ``{step: count}`` (``-1`` for a step that failed)."""
    now = now or datetime.now(UTC)
    factory = session_factory or AsyncSessionLocal
    counts: dict[str, int] = {}
    for name, step in _steps().items():
        if name == "auto_approved" and settings.AUTO_APPROVE_AFTER_DAYS <= 0:
            counts[name] = 0
            log.info("maintenance.step", step=name, count=0, skipped=True)
            continue
        files: list[str] = []
        try:
            async with factory() as db, db.begin():
                counts[name] = await step(db, now=now, files=files)
        except Exception as exc:
            log.error("maintenance.failed", step=name, error=type(exc).__name__)
            counts[name] = FAILED
            continue
        # Committed: only now may files go (a cancellation above skips this, too).
        if files:
            await asyncio.to_thread(images.delete_files, settings.UPLOAD_DIR, *files)
        log.info("maintenance.step", step=name, count=counts[name])
    return counts


async def run_digest(
    force: bool = False,
    *,
    now: datetime | None = None,
    session_factory: SessionFactory | None = None,
) -> DigestRun | None:
    """Send the admin digest in its own committed transaction (``None``: every send failed)."""
    factory = session_factory or AsyncSessionLocal
    async with factory() as db, db.begin():
        return await send_admin_digest(db, now=now, force=force)


# APScheduler 3.11's AsyncIOExecutor cannot wait for coroutine jobs: ``shutdown`` (whatever
# ``wait`` says) cancels them. A cancelled job's open transaction rolls back in its ``async with``
# block, no file is removed before a commit, and the job simply runs again at its next time. The
# wrappers end the job task quietly instead of re-raising into the executor's error logging.


async def digest_job() -> None:
    try:
        await run_digest()
    except asyncio.CancelledError:
        log.warning("scheduler.job_cancelled", job="admin_digest")
    except Exception as exc:
        log.error("scheduler.job_failed", job="admin_digest", error=type(exc).__name__)


async def maintenance_job() -> None:
    try:
        await run_maintenance()
    except asyncio.CancelledError:
        log.warning("scheduler.job_cancelled", job="maintenance")
    except Exception as exc:
        log.error("scheduler.job_failed", job="maintenance", error=type(exc).__name__)


# --- scheduler --------------------------------------------------------------------------------


def create_scheduler() -> AsyncIOScheduler:
    """A not-yet-started scheduler with the ``admin_digest`` and ``maintenance`` jobs."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    job_options = {
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        "replace_existing": True,
    }
    digest_hour = settings.DIGEST_HOUR_UTC % 24
    scheduler.add_job(
        digest_job,
        CronTrigger(hour=digest_hour, minute=0, timezone=TIMEZONE),
        id="admin_digest",
        name="Admin moderation digest",
        **job_options,
    )
    scheduler.add_job(
        maintenance_job,
        CronTrigger(hour=(digest_hour - 1) % 24, minute=0, timezone=TIMEZONE),
        id="maintenance",
        name="Maintenance sweeps",
        **job_options,
    )
    return scheduler
