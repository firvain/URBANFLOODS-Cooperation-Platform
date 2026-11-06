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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import moderation as crud_moderation
from app.crud import stats as crud_stats
from app.crud.audit import SECURITY_AUDIT_ACTIONS
from app.db.enums import CategoryKind, ContentStatus, ReportStatus, TokenPurpose
from app.db.models import (
    Attachment,
    AuditLog,
    Comment,
    EmailToken,
    NotificationPreference,
    Post,
    Reply,
    Report,
    Session,
    Thread,
    User,
)
from app.services import scheduler
from app.services.scheduler import (
    MAINTENANCE_STEPS,
    purge_deleted_content,
    purge_security_audit,
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
    create_report,
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


async def test_sweep_keeps_an_image_another_member_embeds(db_session, uploads) -> None:
    """7m: the sweep counts anyone's content, whoever uploaded the image."""
    uploader = await create_verified_user(db_session)
    other = await create_verified_user(db_session)
    inline = await _upload(db_session, uploads, age=OLD, uploader=uploader)
    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id, author_id=other.id)
    post.body_html = (
        f'<p><img src="https://cooperation.urbanfloods.app{settings.UPLOAD_URL_PREFIX}/'
        f'{inline.storage_path}" alt="A map"></p>'
    )
    await db_session.flush()

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert await _exists(db_session, Attachment, inline.id)


async def test_sweep_deletes_an_image_only_mentioned_as_text(db_session, uploads) -> None:
    """7m: a plain-text mention of the path is not a use."""
    mentioned = await _upload(db_session, uploads, age=OLD)
    await _body_with(
        db_session,
        "post",
        f"<p>Saved at {settings.UPLOAD_URL_PREFIX}/{mentioned.storage_path}</p>",
    )

    await sweep_orphan_uploads(db_session, now=NOW, files=[])

    assert not await _exists(db_session, Attachment, mentioned.id)


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


EXPECTED_KEYS = {
    "sessions",
    "tokens",
    "unverified_users",
    "orphan_uploads",
    "auto_approved",
    "deleted_content",
    "audit_retention",
}


def test_audit_retention_is_the_last_step() -> None:
    assert MAINTENANCE_STEPS[-1] == "audit_retention"
    assert list(scheduler._steps()) == list(MAINTENANCE_STEPS)


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


# --- 7a: deleted content retention ------------------------------------------------------------

# Long ago, so only this section's rows are older than the retention limit at this ``now``.
LONG_AGO = datetime(2002, 1, 1, tzinfo=UTC)
DUE = LONG_AGO - timedelta(days=8)
NOT_DUE = LONG_AGO - timedelta(days=6)
D = ContentStatus.DELETED


async def _deleted_post(db, deleted_at: datetime | None, **kw) -> Post:
    category = await create_category(db)
    status = kw.pop("status", D)
    post = await create_post(
        db, category_id=category.id, status=status, deleted_at=deleted_at, **kw
    )
    post.published_at = LONG_AGO - timedelta(days=30)
    await db.flush()
    return post


async def _deleted_thread(db, deleted_at: datetime | None, **kw) -> Thread:
    category = await create_category(db, kind=CategoryKind.FORUM)
    thread = await create_thread(
        db, category_id=category.id, status=kw.pop("status", D), deleted_at=deleted_at, **kw
    )
    thread.published_at = LONG_AGO - timedelta(days=30)
    await db.flush()
    return thread


async def _live_thread(db) -> Thread:
    category = await create_category(db, kind=CategoryKind.FORUM)
    return await create_thread(db, category_id=category.id)


async def _live_post(db) -> Post:
    category = await create_category(db)
    return await create_post(db, category_id=category.id)


async def test_deleted_content_purges_posts_and_threads_past_the_limit(db_session) -> None:
    old_post = await _deleted_post(db_session, DUE)
    old_thread = await _deleted_thread(db_session, DUE)
    young = await _deleted_post(db_session, NOT_DUE)
    live = await _deleted_post(db_session, None, status=ContentStatus.PUBLISHED)
    ids = old_post.id, old_thread.id, young.id, live.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 2
    assert not await _exists(db_session, Post, ids[0])
    assert not await _exists(db_session, Thread, ids[1])
    assert await _exists(db_session, Post, ids[2])
    assert await _exists(db_session, Post, ids[3])


async def test_deleted_content_respects_the_day_boundary(db_session) -> None:
    exactly = await _deleted_post(db_session, LONG_AGO - timedelta(days=7))
    just_over = await _deleted_post(db_session, LONG_AGO - timedelta(days=7, seconds=1))
    ids = exactly.id, just_over.id

    await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert await _exists(db_session, Post, ids[0])
    assert not await _exists(db_session, Post, ids[1])


async def test_deleted_content_keeps_restored_items(db_session) -> None:
    admin = await create_verified_user(db_session)
    post = await _deleted_post(db_session, DUE)
    await crud_moderation.restore(db_session, content=post, actor=admin, now=LONG_AGO)
    post_id = post.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 0
    assert await _exists(db_session, Post, post_id)


async def test_deleted_content_uses_the_setting(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DELETED_CONTENT_RETENTION_DAYS", 3)
    post = await _deleted_post(db_session, LONG_AGO - timedelta(days=4))

    assert await purge_deleted_content(db_session, now=LONG_AGO, files=[]) == 1
    assert not await _exists(db_session, Post, post.id)


async def test_deleted_content_is_off_when_the_setting_is_0(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DELETED_CONTENT_RETENTION_DAYS", 0)
    post = await _deleted_post(db_session, LONG_AGO - timedelta(days=400))

    assert await purge_deleted_content(db_session, now=LONG_AGO, files=[]) == 0
    assert await _exists(db_session, Post, post.id)
    assert await _audit(db_session, "maintenance.deleted_content") == []


async def test_deleted_content_purges_old_comments_and_replies(db_session) -> None:
    post = await _live_post(db_session)
    thread = await _live_thread(db_session)
    old_comment = await create_comment(db_session, post_id=post.id, status=D, deleted_at=DUE)
    young_comment = await create_comment(db_session, post_id=post.id, status=D, deleted_at=NOT_DUE)
    live_comment = await create_comment(db_session, post_id=post.id)
    old_reply = await create_reply(db_session, thread_id=thread.id, status=D, deleted_at=DUE)
    young_reply = await create_reply(db_session, thread_id=thread.id, status=D, deleted_at=NOT_DUE)
    ids = old_comment.id, young_comment.id, live_comment.id, old_reply.id, young_reply.id
    parents = post.id, thread.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 2
    assert not await _exists(db_session, Comment, ids[0])
    assert await _exists(db_session, Comment, ids[1])
    assert await _exists(db_session, Comment, ids[2])
    assert not await _exists(db_session, Reply, ids[3])
    assert await _exists(db_session, Reply, ids[4])
    assert await _exists(db_session, Post, parents[0])
    assert await _exists(db_session, Thread, parents[1])


@pytest.mark.parametrize(
    "child_fields",
    [
        {},  # published: another member's reply, shown under the placeholder
        {"status": ContentStatus.HIDDEN},
        # Deleted, but more recently: it still has its own days to be restored.
        {"status": ContentStatus.DELETED, "deleted_at": NOT_DUE},
    ],
)
async def test_deleted_reply_with_a_live_child_is_kept(db_session, child_fields) -> None:
    """A deleted reply that still holds replies is shown as a placeholder: purging it would
    delete those replies with it."""
    thread = await _live_thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id, status=D, deleted_at=DUE)
    child = await create_reply(
        db_session, thread_id=thread.id, parent_reply_id=parent.id, **child_fields
    )
    ids = parent.id, child.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 0
    assert await _exists(db_session, Reply, ids[0])
    assert await _exists(db_session, Reply, ids[1])


async def test_deleted_reply_whose_children_are_all_due_is_purged(db_session) -> None:
    thread = await _live_thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id, status=D, deleted_at=DUE)
    child = await create_reply(
        db_session,
        thread_id=thread.id,
        parent_reply_id=parent.id,
        status=D,
        deleted_at=DUE - timedelta(days=1),
    )
    ids = parent.id, child.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 2
    assert not await _exists(db_session, Reply, ids[0])
    assert not await _exists(db_session, Reply, ids[1])


async def test_deleted_content_audits_each_purge_and_a_summary(db_session) -> None:
    post = await _deleted_post(db_session, DUE)
    comment = await create_comment(db_session, post_id=post.id)
    thread = await _deleted_thread(db_session, DUE - timedelta(hours=1))
    ids = post.id, comment.id, thread.id

    count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 2
    purges = [
        row
        for row in await _audit(db_session, "moderation.purge")
        if (row.target_type, row.target_id) in {("post", ids[0]), ("thread", ids[2])}
    ]
    # Oldest first: the thread was deleted an hour before the post.
    assert [(row.target_type, row.target_id) for row in purges] == [
        ("thread", ids[2]),
        ("post", ids[0]),
    ]
    for row in purges:
        assert row.actor_id is None
        assert row.metadata_["reason"] == "retention"
    assert purges[1].metadata_["children_deleted"] == 1
    (summary,) = await _audit(db_session, "maintenance.deleted_content")
    assert summary.actor_id is None
    assert summary.metadata_ == {"count": 2}
    assert not await _exists(db_session, Comment, ids[1])


async def test_deleted_content_with_nothing_due_writes_no_audit(db_session) -> None:
    await _deleted_post(db_session, NOT_DUE)

    assert await purge_deleted_content(db_session, now=LONG_AGO, files=[]) == 0
    assert await _audit(db_session, "maintenance.deleted_content") == []


async def test_deleted_content_resolves_open_reports_by_nobody(db_session) -> None:
    reporter = await create_verified_user(db_session)
    post = await _deleted_post(db_session, DUE)
    report = await create_report(
        db_session, reporter_id=reporter.id, content_type="post", content_id=post.id
    )
    report_id = report.id

    await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    db_session.expire_all()
    report = await db_session.get(Report, report_id)
    assert report.status == ReportStatus.RESOLVED
    assert report.resolved_by is None


async def test_deleted_content_collects_freed_files(db_session, uploads) -> None:
    image = await _upload(db_session, uploads, age=OLD)
    rel_paths = [image.storage_path, image.thumb_path]
    post = await _deleted_post(db_session, DUE)
    post.body_html = f'<img src="{settings.UPLOAD_URL_PREFIX}/{image.storage_path}" alt="x">'
    await db_session.flush()
    files: list[str] = []

    await purge_deleted_content(db_session, now=LONG_AGO, files=files)

    assert set(rel_paths) <= set(files)
    # Removed by the caller only after the commit.
    assert all((uploads / rel).exists() for rel in rel_paths)


async def test_deleted_content_caps_one_run(db_session, monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "MAX_DELETED_PURGES_PER_RUN", 2)
    posts = [await _deleted_post(db_session, DUE - timedelta(hours=i)) for i in range(3)]
    ids = [post.id for post in posts]

    with structlog.testing.capture_logs() as logs:
        count = await purge_deleted_content(db_session, now=LONG_AGO, files=[])

    assert count == 2
    # Oldest first: the first post (deleted last) is left for the next run.
    assert await _exists(db_session, Post, ids[0])
    assert not await _exists(db_session, Post, ids[1])
    assert not await _exists(db_session, Post, ids[2])
    capped = [e for e in logs if e["event"] == "maintenance.capped"]
    assert capped == [
        {"event": "maintenance.capped", "step": "deleted_content", "limit": 2, "log_level": "info"}
    ]


async def test_run_maintenance_purges_deleted_content_and_files_after_commit(
    tx_factory, uploads
) -> None:
    async with tx_factory() as db:
        image = await _upload(db, uploads, age=timedelta(hours=1))
        rel_paths = [image.storage_path, image.thumb_path]
        post = await _deleted_post(db, DUE)
        post.body_html = f'<img src="{settings.UPLOAD_URL_PREFIX}/{image.storage_path}" alt="x">'
        post_id, image_id = post.id, image.id
        await db.commit()

    counts = await run_maintenance(LONG_AGO, session_factory=tx_factory)

    assert counts["deleted_content"] == 1
    assert not any((uploads / rel).exists() for rel in rel_paths)
    async with tx_factory() as db:
        assert await db.get(Post, post_id) is None
        assert await db.get(Attachment, image_id) is None


async def test_run_maintenance_skips_deleted_content_when_off(
    tx_factory, uploads, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DELETED_CONTENT_RETENTION_DAYS", 0)
    async with tx_factory() as db:
        post = await _deleted_post(db, DUE)
        post_id = post.id
        await db.commit()

    with structlog.testing.capture_logs() as logs:
        counts = await run_maintenance(LONG_AGO, session_factory=tx_factory)

    assert counts["deleted_content"] == 0
    (event,) = [
        e for e in logs if e["event"] == "maintenance.step" and e["step"] == "deleted_content"
    ]
    assert event["skipped"] is True
    async with tx_factory() as db:
        assert await db.get(Post, post_id) is not None


async def test_failed_deleted_content_transaction_keeps_rows_and_files(
    tx_factory, uploads, monkeypatch
) -> None:
    async with tx_factory() as db:
        image = await _upload(db, uploads, age=timedelta(hours=1))
        rel_paths = [image.storage_path, image.thumb_path]
        post = await _deleted_post(db, DUE)
        post.body_html = f'<img src="{settings.UPLOAD_URL_PREFIX}/{image.storage_path}" alt="x">'
        post_id = post.id
        await db.commit()
    real_log_action = scheduler.log_action

    async def failing_log_action(db, **kwargs):
        if kwargs.get("action") == "maintenance.deleted_content":
            raise RuntimeError("audit down")
        return await real_log_action(db, **kwargs)

    monkeypatch.setattr(scheduler, "log_action", failing_log_action)

    counts = await run_maintenance(LONG_AGO, session_factory=tx_factory)

    assert counts["deleted_content"] == -1
    assert all((uploads / rel).exists() for rel in rel_paths)
    async with tx_factory() as db:
        assert await db.get(Post, post_id) is not None


# --- 7r: security-event retention in the audit log --------------------------------------------

# Long ago, so only this section's rows are older than the cutoff at this ``now``.
AUDIT_NOW = datetime(1998, 1, 1, tzinfo=UTC)
AUDIT_DUE = AUDIT_NOW - timedelta(days=366)
AUDIT_NOT_DUE = AUDIT_NOW - timedelta(days=364)

KEPT_ACTIONS = [
    "auth.register",
    "auth.consent",
    "auth.email_verified",
    "auth.profile_updated",
    "auth.notifications_updated",
    "auth.data_exported",
    "auth.account_deleted",
    "moderation.approve",
    "report.dismiss",
    "post.created",
    "maintenance.purge_unverified",
]


async def _audit_row(
    db, action: str, created_at: datetime, actor_id: int | None = None
) -> AuditLog:
    row = AuditLog(action=action, created_at=created_at, actor_id=actor_id)
    db.add(row)
    await db.flush()
    return row


@pytest.mark.parametrize("action", sorted(SECURITY_AUDIT_ACTIONS))
async def test_audit_retention_deletes_old_security_events(db_session, action) -> None:
    row = await _audit_row(db_session, action, AUDIT_DUE)

    count = await purge_security_audit(db_session, now=AUDIT_NOW)

    assert count == 1
    assert not await _exists(db_session, AuditLog, row.id)


async def test_audit_retention_keeps_recent_security_events(db_session) -> None:
    rows = [await _audit_row(db_session, a, AUDIT_NOT_DUE) for a in sorted(SECURITY_AUDIT_ACTIONS)]
    ids = [row.id for row in rows]

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 0
    for row_id in ids:
        assert await _exists(db_session, AuditLog, row_id)


async def test_audit_retention_respects_the_day_boundary(db_session) -> None:
    days = settings.SECURITY_AUDIT_RETENTION_DAYS
    just_over = await _audit_row(
        db_session, "auth.login", AUDIT_NOW - timedelta(days=days, seconds=1)
    )
    exactly = await _audit_row(db_session, "auth.login", AUDIT_NOW - timedelta(days=days))
    recent = await _audit_row(db_session, "auth.login", AUDIT_NOW - timedelta(days=days - 1))
    ids = just_over.id, exactly.id, recent.id

    await purge_security_audit(db_session, now=AUDIT_NOW)

    assert not await _exists(db_session, AuditLog, ids[0])
    assert await _exists(db_session, AuditLog, ids[1])
    assert await _exists(db_session, AuditLog, ids[2])


@pytest.mark.parametrize("action", KEPT_ACTIONS)
async def test_audit_retention_keeps_other_old_rows(db_session, action) -> None:
    assert action not in SECURITY_AUDIT_ACTIONS
    row = await _audit_row(db_session, action, AUDIT_NOW - timedelta(days=5000))

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 0
    assert await _exists(db_session, AuditLog, row.id)


async def test_audit_retention_uses_the_setting(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECURITY_AUDIT_RETENTION_DAYS", 30)
    due = await _audit_row(db_session, "auth.logout", AUDIT_NOW - timedelta(days=31))
    kept = await _audit_row(db_session, "auth.logout", AUDIT_NOW - timedelta(days=29))
    ids = due.id, kept.id

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 1
    assert not await _exists(db_session, AuditLog, ids[0])
    assert await _exists(db_session, AuditLog, ids[1])


def test_security_audit_retention_defaults_to_a_year() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["SECURITY_AUDIT_RETENTION_DAYS"].default == 365


async def test_audit_retention_is_off_when_the_setting_is_0(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECURITY_AUDIT_RETENTION_DAYS", 0)
    row = await _audit_row(db_session, "auth.login", AUDIT_NOW - timedelta(days=5000))

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 0
    assert await _exists(db_session, AuditLog, row.id)
    assert await _audit(db_session, "maintenance.audit_retention") == []


async def test_audit_retention_caps_one_run(db_session, monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "MAX_AUDIT_PURGES_PER_RUN", 2)
    rows = [
        await _audit_row(db_session, "auth.login", AUDIT_DUE - timedelta(hours=i)) for i in range(3)
    ]
    ids = [row.id for row in rows]

    with structlog.testing.capture_logs() as logs:
        count = await purge_security_audit(db_session, now=AUDIT_NOW)

    assert count == 2
    # Oldest first: the first row (the newest) is left for the next run.
    assert await _exists(db_session, AuditLog, ids[0])
    assert not await _exists(db_session, AuditLog, ids[1])
    assert not await _exists(db_session, AuditLog, ids[2])
    capped = [e for e in logs if e["event"] == "maintenance.capped"]
    assert capped == [
        {"event": "maintenance.capped", "step": "audit_retention", "limit": 2, "log_level": "info"}
    ]


async def test_audit_retention_writes_one_audit_row_with_count_only(db_session) -> None:
    for action in ("auth.login", "auth.login_failed"):
        await _audit_row(db_session, action, AUDIT_DUE)

    count = await purge_security_audit(db_session, now=AUDIT_NOW)

    assert count == 2
    (summary,) = await _audit(db_session, "maintenance.audit_retention")
    assert summary.actor_id is None
    assert summary.target_type is None and summary.target_id is None
    assert summary.metadata_ == {"count": 2}
    assert "maintenance.audit_retention" not in SECURITY_AUDIT_ACTIONS


async def test_audit_retention_with_nothing_due_writes_no_audit(db_session) -> None:
    await _audit_row(db_session, "auth.login", AUDIT_NOT_DUE)

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 0
    assert await _audit(db_session, "maintenance.audit_retention") == []


async def test_sign_in_statistic_still_counts_logins_in_the_window(db_session) -> None:
    """The step keeps the last year of ``auth.login`` rows, which the export counts."""
    member = await create_verified_user(db_session)
    await _audit_row(db_session, "auth.login", AUDIT_NOW - timedelta(days=10), member.id)
    await _audit_row(db_session, "auth.login", AUDIT_NOW - timedelta(days=5), member.id)
    old = await _audit_row(db_session, "auth.login", AUDIT_DUE, member.id)
    old_id = old.id

    assert await purge_security_audit(db_session, now=AUDIT_NOW) == 1

    assert not await _exists(db_session, AuditLog, old_id)
    stats = await crud_stats.export_stats(
        db_session, start=date(1997, 12, 1), end=date(1997, 12, 31)
    )
    assert stats.logged_in == 1


async def test_run_maintenance_purges_old_security_events(tx_factory) -> None:
    async with tx_factory() as db:
        due = await _audit_row(db, "auth.login", AUDIT_DUE)
        kept = await _audit_row(db, "auth.consent", AUDIT_DUE)
        ids = due.id, kept.id
        await db.commit()

    counts = await run_maintenance(AUDIT_NOW, session_factory=tx_factory)

    assert counts["audit_retention"] == 1
    async with tx_factory() as db:
        assert await db.get(AuditLog, ids[0]) is None
        assert await db.get(AuditLog, ids[1]) is not None
        (summary,) = await _audit(db, "maintenance.audit_retention")
        assert summary.metadata_ == {"count": 1}


async def test_run_maintenance_skips_audit_retention_session_when_disabled(
    tx_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SECURITY_AUDIT_RETENTION_DAYS", 0)
    called = []

    async def spy(db, **kwargs):
        called.append(kwargs)
        return 0

    monkeypatch.setattr(scheduler.crud_audit, "purge_security_events", spy)

    with structlog.testing.capture_logs() as logs:
        counts = await run_maintenance(AUDIT_NOW, session_factory=tx_factory)

    assert called == []
    assert counts["audit_retention"] == 0
    (event,) = [
        e for e in logs if e["event"] == "maintenance.step" and e["step"] == "audit_retention"
    ]
    assert event["skipped"] is True
