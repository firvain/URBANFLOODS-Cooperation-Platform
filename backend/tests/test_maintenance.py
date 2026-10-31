"""Increment 4e: maintenance sweeps (``services/scheduler.py``): purge of stale unverified
accounts, orphan upload sweep, auto-approval, and ``run_maintenance``.

The step functions are tested on ``db_session`` (rolled back). ``run_maintenance`` opens its own
sessions and commits, so it gets a session factory joined to an outer transaction that is rolled
back (``tx_factory``).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus, TokenPurpose
from app.db.models import (
    Attachment,
    AuditLog,
    EmailToken,
    NotificationPreference,
    Post,
    Session,
    User,
)
from app.services import scheduler
from app.services.scheduler import (
    MAINTENANCE_STEPS,
    purge_unverified_users,
    run_maintenance,
    sweep_orphan_uploads,
)
from tests.factories import (
    create_attachment,
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_thread,
    create_user,
    create_verified_user,
)

NOW = datetime.now(UTC)


async def _exists(db, model, pk) -> bool:
    db.expire_all()
    return (await db.get(model, pk)) is not None


async def _audit(db, action: str) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
    return list((await db.scalars(stmt)).all())


def _hash() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


# --- unverified purge -------------------------------------------------------------------------


async def test_purge_deletes_stale_unverified_users_with_their_rows(db_session) -> None:
    stale = await create_user(db_session, created_at=NOW - timedelta(days=31))
    db_session.add(Session(user_id=stale.id, token_hash=_hash(), expires_at=NOW))
    db_session.add(
        EmailToken(
            user_id=stale.id,
            purpose=TokenPurpose.VERIFY_EMAIL,
            token_hash=_hash(),
            expires_at=NOW,
        )
    )
    await db_session.flush()
    stale_id = stale.id

    count = await purge_unverified_users(db_session, now=NOW)

    assert count >= 1
    assert not await _exists(db_session, User, stale_id)
    assert not await _exists(db_session, NotificationPreference, stale_id)
    assert await db_session.scalar(select(func.count()).where(Session.user_id == stale_id)) == 0
    assert await db_session.scalar(select(func.count()).where(EmailToken.user_id == stale_id)) == 0


async def test_purge_respects_the_day_boundary(db_session) -> None:
    days = settings.UNVERIFIED_PURGE_DAYS
    just_over = await create_user(db_session, created_at=NOW - timedelta(days=days, seconds=1))
    exactly = await create_user(db_session, created_at=NOW - timedelta(days=days))
    recent = await create_user(db_session, created_at=NOW - timedelta(days=days - 1))
    ids = just_over.id, exactly.id, recent.id

    await purge_unverified_users(db_session, now=NOW)

    assert not await _exists(db_session, User, ids[0])
    assert await _exists(db_session, User, ids[1])
    assert await _exists(db_session, User, ids[2])


async def test_purge_uses_the_setting(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UNVERIFIED_PURGE_DAYS", 3)
    user = await create_user(db_session, created_at=NOW - timedelta(days=4))

    await purge_unverified_users(db_session, now=NOW)

    assert not await _exists(db_session, User, user.id)


async def test_purge_skips_verified_and_deleted_users(db_session) -> None:
    old = NOW - timedelta(days=90)
    verified = await create_verified_user(db_session, created_at=old)
    deleted = await create_user(db_session, created_at=old, deleted_at=old)
    ids = verified.id, deleted.id

    await purge_unverified_users(db_session, now=NOW)

    assert await _exists(db_session, User, ids[0])
    assert await _exists(db_session, User, ids[1])


async def test_purge_writes_one_audit_row_with_count_only(db_session) -> None:
    for _ in range(2):
        await create_user(db_session, created_at=NOW - timedelta(days=40))

    count = await purge_unverified_users(db_session, now=NOW)

    rows = await _audit(db_session, "maintenance.purge_unverified")
    assert len(rows) == 1
    assert rows[0].actor_id is None
    assert rows[0].target_id is None
    assert rows[0].metadata_ == {"count": count}
    assert count >= 2


async def test_purge_with_nothing_to_do_writes_no_audit(db_session) -> None:
    # Far in the past: nothing was created before 2000.
    count = await purge_unverified_users(db_session, now=datetime(2000, 1, 1, tzinfo=UTC))

    assert count == 0
    assert await _audit(db_session, "maintenance.purge_unverified") == []


# --- orphan uploads ---------------------------------------------------------------------------


@pytest.fixture
def uploads(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


async def _upload(db, uploads: Path, *, age: timedelta, uploader: User | None = None) -> Attachment:
    attachment = await create_attachment(db, uploader_id=uploader.id if uploader else None)
    attachment.created_at = NOW - age
    await db.flush()
    for rel in (attachment.storage_path, attachment.thumb_path):
        target = uploads / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"webp")
    return attachment


OLD = timedelta(hours=25)


async def test_sweep_deletes_old_orphan_rows_and_collects_their_files(db_session, uploads) -> None:
    orphan = await _upload(db_session, uploads, age=OLD)
    orphan_id = orphan.id
    rel_paths = [orphan.storage_path, orphan.thumb_path]
    files: list[str] = []

    count = await sweep_orphan_uploads(db_session, now=NOW, files=files)

    assert count >= 1
    assert not await _exists(db_session, Attachment, orphan_id)
    assert set(rel_paths) <= set(files)
    # Files are removed by the caller only after the commit.
    assert all((uploads / rel).exists() for rel in rel_paths)


async def test_sweep_keeps_recent_uploads(db_session, uploads) -> None:
    recent = await _upload(db_session, uploads, age=timedelta(hours=23))

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, recent.id)
    assert (uploads / recent.storage_path).exists()


async def test_sweep_uses_the_setting(db_session, uploads, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ORPHAN_UPLOAD_HOURS", 2)
    upload = await _upload(db_session, uploads, age=timedelta(hours=3))

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert not await _exists(db_session, Attachment, upload.id)


async def test_sweep_keeps_post_covers(db_session, uploads) -> None:
    cover = await _upload(db_session, uploads, age=OLD)
    category = await create_category(db_session)
    await create_post(db_session, category_id=category.id, cover_attachment_id=cover.id)

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, cover.id)
    assert (uploads / cover.storage_path).exists()


async def test_sweep_keeps_avatars(db_session, uploads) -> None:
    user = await create_verified_user(db_session)
    avatar = await _upload(db_session, uploads, age=OLD, uploader=user)
    user.avatar_attachment_id = avatar.id
    await db_session.flush()

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, avatar.id)


async def _body_with(db, kind: str, html: str) -> None:
    category = await create_category(
        db, kind=CategoryKind.FORUM if kind in {"thread", "reply"} else CategoryKind.BLOG
    )
    if kind == "post":
        row = await create_post(db, category_id=category.id)
    elif kind == "comment":
        post = await create_post(db, category_id=category.id)
        row = await create_comment(db, post_id=post.id)
    else:
        thread = await create_thread(db, category_id=category.id)
        row = thread if kind == "thread" else await create_reply(db, thread_id=thread.id)
    row.body_html = html
    await db.flush()


@pytest.mark.parametrize("kind", ["post", "thread", "reply", "comment"])
async def test_sweep_keeps_images_referenced_in_bodies(db_session, uploads, kind) -> None:
    inline = await _upload(db_session, uploads, age=OLD)
    await _body_with(
        db_session,
        kind,
        f'<p><img src="{settings.UPLOAD_URL_PREFIX}/{inline.storage_path}" alt="A map"></p>',
    )

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, inline.id)
    assert (uploads / inline.storage_path).exists()


async def test_sweep_keeps_images_referenced_by_thumbnail(db_session, uploads) -> None:
    inline = await _upload(db_session, uploads, age=OLD)
    await _body_with(
        db_session,
        "post",
        f'<p><img src="{settings.UPLOAD_URL_PREFIX}/{inline.thumb_path}" alt="A map"></p>',
    )

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, inline.id)


async def test_sweep_keeps_images_referenced_by_deleted_content(db_session, uploads) -> None:
    """Soft-deleted content can be restored, so its images stay."""
    inline = await _upload(db_session, uploads, age=OLD)
    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id, status=ContentStatus.DELETED)
    post.body_html = f'<img src="{settings.UPLOAD_URL_PREFIX}/{inline.storage_path}" alt="x">'
    await db_session.flush()

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, inline.id)


async def test_sweep_removes_soft_deleted_orphan_rows(db_session, uploads) -> None:
    gone = await _upload(db_session, uploads, age=OLD)
    gone.deleted_at = NOW - OLD
    await db_session.flush()

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert not await _exists(db_session, Attachment, gone.id)


async def test_sweep_writes_audit_row_with_count(db_session, uploads) -> None:
    await _upload(db_session, uploads, age=OLD)
    await _upload(db_session, uploads, age=OLD)

    count = await sweep_orphan_uploads(db_session, now=NOW, files=[])

    rows = await _audit(db_session, "maintenance.orphan_uploads")
    assert len(rows) == 1
    assert rows[0].actor_id is None
    assert rows[0].metadata_ == {"count": count}
    assert count >= 2


# --- run_maintenance --------------------------------------------------------------------------


@pytest.fixture
async def tx_factory(database_url: str) -> AsyncIterator[Callable[[], AsyncSession]]:
    """A session factory whose sessions join one outer transaction (commits become savepoint
    releases); everything is rolled back afterwards."""
    from app.db.session import engine

    async with engine.connect() as conn:
        outer = await conn.begin()

        def factory() -> AsyncSession:
            return AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        try:
            yield factory
        finally:
            await outer.rollback()


EXPECTED_KEYS = {"sessions", "tokens", "unverified_users", "orphan_uploads", "auto_approved"}


async def test_run_maintenance_returns_counts_per_step(tx_factory, uploads) -> None:
    async with tx_factory() as db:
        stale = await create_user(db, created_at=NOW - timedelta(days=31))
        stale_id = stale.id
        await _upload(db, uploads, age=OLD)
        await db.commit()

    counts = await run_maintenance(NOW, session_factory=tx_factory)

    assert set(counts) == EXPECTED_KEYS == set(MAINTENANCE_STEPS)
    assert all(isinstance(value, int) for value in counts.values())
    assert counts["unverified_users"] >= 1
    assert counts["orphan_uploads"] >= 1
    assert counts["auto_approved"] == 0
    async with tx_factory() as db:
        assert await db.get(User, stale_id) is None


async def test_run_maintenance_logs_each_count(tx_factory, uploads) -> None:
    with structlog.testing.capture_logs() as logs:
        counts = await run_maintenance(NOW, session_factory=tx_factory)

    done = {e["step"]: e["count"] for e in logs if e["event"] == "maintenance.step"}
    assert done == counts


async def test_run_maintenance_auto_approves_only_when_enabled(
    tx_factory, uploads, monkeypatch
) -> None:
    async with tx_factory() as db:
        author = await create_verified_user(db)
        category = await create_category(db)
        post = await create_post(
            db,
            category_id=category.id,
            author_id=author.id,
            status=ContentStatus.PENDING,
            created_at=NOW - timedelta(days=10),
        )
        post_id = post.id
        await db.commit()

    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 0)
    counts = await run_maintenance(NOW, session_factory=tx_factory)
    assert counts["auto_approved"] == 0
    async with tx_factory() as db:
        assert (await db.get(Post, post_id)).status == ContentStatus.PENDING

    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 7)
    counts = await run_maintenance(NOW, session_factory=tx_factory)
    assert counts["auto_approved"] >= 1
    async with tx_factory() as db:
        assert (await db.get(Post, post_id)).status == ContentStatus.PUBLISHED


async def test_run_maintenance_skips_auto_approve_session_when_disabled(
    tx_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 0)
    called = []

    async def spy(db, *, now=None):
        called.append(now)
        return 0

    monkeypatch.setattr(scheduler.crud_moderation, "auto_approve_stale", spy)

    await run_maintenance(NOW, session_factory=tx_factory)

    assert called == []


async def test_failed_step_does_not_stop_the_others(tx_factory, monkeypatch) -> None:
    async def boom(db, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(scheduler, "sweep_orphan_uploads", boom)

    with structlog.testing.capture_logs() as logs:
        counts = await run_maintenance(NOW, session_factory=tx_factory)

    assert counts["orphan_uploads"] == -1
    assert counts["sessions"] >= 0 and counts["auto_approved"] == 0
    failed = [e for e in logs if e["event"] == "maintenance.failed"]
    assert [(e["step"], e["error"]) for e in failed] == [("orphan_uploads", "RuntimeError")]


async def test_run_maintenance_unlinks_orphan_files_after_commit(tx_factory, uploads) -> None:
    async with tx_factory() as db:
        orphan = await _upload(db, uploads, age=OLD)
        orphan_id, rel_paths = orphan.id, [orphan.storage_path, orphan.thumb_path]
        await db.commit()

    counts = await run_maintenance(NOW, session_factory=tx_factory)

    assert counts["orphan_uploads"] >= 1
    assert not any((uploads / rel).exists() for rel in rel_paths)
    async with tx_factory() as db:
        assert await db.get(Attachment, orphan_id) is None


@pytest.mark.parametrize("error", [RuntimeError("audit down"), asyncio.CancelledError()])
async def test_failed_orphan_transaction_keeps_rows_and_files(
    tx_factory, uploads, monkeypatch, error
) -> None:
    async with tx_factory() as db:
        orphan = await _upload(db, uploads, age=OLD)
        orphan_id, rel_paths = orphan.id, [orphan.storage_path, orphan.thumb_path]
        await db.commit()
    real_log_action = scheduler.log_action

    async def failing_log_action(db, **kwargs):
        if kwargs.get("action") == "maintenance.orphan_uploads":
            raise error
        return await real_log_action(db, **kwargs)

    monkeypatch.setattr(scheduler, "log_action", failing_log_action)
    unlinked: list[tuple] = []
    monkeypatch.setattr(scheduler.images, "delete_files", lambda *a: unlinked.append(a))

    if isinstance(error, asyncio.CancelledError):
        # A job cancelled at shutdown: the transaction rolls back, the cancellation propagates.
        with pytest.raises(asyncio.CancelledError):
            await run_maintenance(NOW, session_factory=tx_factory)
    else:
        counts = await run_maintenance(NOW, session_factory=tx_factory)
        assert counts["orphan_uploads"] == -1

    assert unlinked == []
    assert all((uploads / rel).exists() for rel in rel_paths)
    async with tx_factory() as db:
        assert await db.get(Attachment, orphan_id) is not None
