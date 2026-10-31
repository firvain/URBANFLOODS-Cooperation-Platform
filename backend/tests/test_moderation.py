"""Increment 4b: ``crud/moderation.py`` - the content state machine (approve, reject, hide,
unhide, delete, restore), auto-hide on reports, the pending queue and the auto-approve sweep.

Every test runs inside the ``db_session`` transaction and only flushes, so the fixture's rollback
leaves no rows behind. Content is created in fresh categories.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import moderation
from app.crud.tag import recount_tag_usage
from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason, ReportStatus
from app.db.models import AuditLog, Post, Tag, Thread
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_report,
    create_tag,
    create_thread,
    create_user,
    create_verified_user,
)

P = ContentStatus.PENDING
PUB = ContentStatus.PUBLISHED
H = ContentStatus.HIDDEN
D = ContentStatus.DELETED
ACTIONS = ("approve", "reject", "hide", "unhide", "delete", "restore")
ALLOWED = {
    (P, "approve"): PUB,
    (P, "reject"): H,
    (P, "delete"): D,
    (PUB, "hide"): H,
    (PUB, "delete"): D,
    (H, "unhide"): PUB,
    (H, "delete"): D,
    (D, "restore"): PUB,
}
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


# --- helpers ----------------------------------------------------------------------------------


async def _make(db, content_type: ContentType, status: ContentStatus, *, author_id=None, **kw):
    """A post/thread/reply/comment in ``status`` (hidden ones by an admin; deleted ones had been
    published)."""
    extra: dict = {}
    if status == H:
        extra["hidden_reason"] = HiddenReason.ADMIN
    if status == D:
        extra["deleted_at"] = NOW - timedelta(days=1)
    if content_type in (ContentType.POST, ContentType.COMMENT):
        category = await create_category(db, kind=CategoryKind.BLOG)
        if content_type == ContentType.POST:
            obj = await create_post(
                db, category_id=category.id, status=status, author_id=author_id, **extra, **kw
            )
            if status in (H, D):
                obj.published_at = NOW - timedelta(days=2)
                await db.flush()
            return obj
        post = await create_post(db, category_id=category.id)
        return await create_comment(
            db, post_id=post.id, status=status, author_id=author_id, **extra, **kw
        )
    category = await create_category(db, kind=CategoryKind.FORUM)
    if content_type == ContentType.THREAD:
        obj = await create_thread(
            db, category_id=category.id, status=status, author_id=author_id, **extra, **kw
        )
        if status in (H, D):
            obj.published_at = NOW - timedelta(days=2)
            await db.flush()
        return obj
    thread = await create_thread(db, category_id=category.id)
    return await create_reply(
        db, thread_id=thread.id, status=status, author_id=author_id, **extra, **kw
    )


async def _call(action: str, db, content, actor, *, reason: str | None = None):
    """Run ``action``; returns the content (``approve``/``unhide`` return an ``Approval``)."""
    fn = getattr(moderation, action)
    if action in ("reject", "hide"):
        return await fn(db, content=content, actor=actor, reason=reason, now=NOW)
    result = await fn(db, content=content, actor=actor, now=NOW)
    return result.content if isinstance(result, moderation.Approval) else result


async def _audits(db, *, action: str | None = None, target_type: str, target_id: int):
    stmt = select(AuditLog).where(
        AuditLog.target_type == target_type, AuditLog.target_id == target_id
    )
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return list((await db.scalars(stmt.order_by(AuditLog.id))).all())


async def _usage(db, tag: Tag) -> int:
    return (await db.execute(select(Tag.usage_count).where(Tag.id == tag.id))).scalar_one()


def _assert_invalid(exc: pytest.ExceptionInfo) -> None:
    assert exc.value.status_code == 409
    assert exc.value.code == "moderation.invalid_transition"


# --- transition matrix (posts and threads) ----------------------------------------------------


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
@pytest.mark.parametrize("start", [P, PUB, H, D])
@pytest.mark.parametrize("action", ACTIONS)
async def test_transition_matrix(db_session, content_type, start, action):
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    content = await _make(db_session, content_type, start, author_id=author.id)
    before_published_at = content.published_at
    expected = ALLOWED.get((start, action))

    if expected is None:
        with pytest.raises(AppError) as exc:
            await _call(action, db_session, content, admin, reason="why")
        _assert_invalid(exc)
        await db_session.refresh(content)
        assert content.status == start
        assert content.published_at == before_published_at
        assert await _audits(db_session, target_type=content_type.value, target_id=content.id) == []
        return

    result = await _call(action, db_session, content, admin, reason="why")
    assert result is content
    await db_session.refresh(content)
    assert content.status == expected
    (row,) = await _audits(
        db_session,
        action=f"moderation.{action}",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert row.actor_id == admin.id
    assert row.metadata_["from"] == start.value
    assert row.metadata_["to"] == expected.value
    if action in ("reject", "hide"):
        assert row.metadata_["reason"] == "why"


async def test_approve_sets_published_and_approval_fields(db_session):
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, P, author_id=author.id)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.published_at == NOW
    assert post.approved_by == admin.id
    assert post.approved_at == NOW


async def test_reject_sets_rejected_reason_and_keeps_author_untrusted(db_session):
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    thread = await _make(db_session, ContentType.THREAD, P, author_id=author.id)

    await moderation.reject(db_session, content=thread, actor=admin, reason="spam", now=NOW)

    assert thread.status == H
    assert thread.hidden_reason == HiddenReason.REJECTED
    assert thread.published_at is None
    assert author.trusted_at is None
    assert (
        await _audits(db_session, action="user.trusted", target_type="user", target_id=author.id)
        == []
    )


async def test_hide_sets_admin_reason(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, PUB)

    await moderation.hide(db_session, content=post, actor=admin, reason=None, now=NOW)

    assert post.status == H
    assert post.hidden_reason == HiddenReason.ADMIN
    (row,) = await _audits(
        db_session, action="moderation.hide", target_type="post", target_id=post.id
    )
    assert "reason" not in row.metadata_


# --- trust ------------------------------------------------------------------------------------


async def test_approve_trusts_author_once(db_session):
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    first = await _make(db_session, ContentType.POST, P, author_id=author.id)
    second = await _make(db_session, ContentType.THREAD, P, author_id=author.id)

    await moderation.approve(db_session, content=first, actor=admin, now=NOW)
    assert author.trusted_at == NOW

    later = NOW + timedelta(hours=3)
    await moderation.approve(db_session, content=second, actor=admin, now=later)
    await db_session.refresh(author)
    assert author.trusted_at == NOW

    rows = await _audits(db_session, action="user.trusted", target_type="user", target_id=author.id)
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_["reason"] == "first_post_approved"


async def test_approve_content_without_author(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, P, author_id=None)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB


# --- unhide -----------------------------------------------------------------------------------


async def test_unhide_resets_report_count_and_dismisses_open_reports(db_session):
    admin = await create_admin(db_session)
    first = await create_user(db_session)
    second = await create_user(db_session)
    third = await create_user(db_session)
    post = await _make(db_session, ContentType.POST, H, report_count=2)
    published_at = post.published_at
    r1 = await create_report(db_session, reporter_id=first.id, content_id=post.id)
    r2 = await create_report(db_session, reporter_id=second.id, content_id=post.id)
    # A report on another content type with the same id stays open.
    other = await create_report(
        db_session, reporter_id=third.id, content_type="thread", content_id=post.id
    )

    await moderation.unhide(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.hidden_reason is None
    assert post.report_count == 0
    assert post.published_at == published_at
    for report in (r1, r2, other):
        await db_session.refresh(report)
    for report in (r1, r2):
        assert report.status == ReportStatus.DISMISSED
        assert report.resolved_by == admin.id
        assert report.resolved_at == NOW
    assert other.status == ReportStatus.OPEN


async def test_unhide_rejected_is_an_approval(db_session):
    admin = await create_admin(db_session)
    other_admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, P, author_id=author.id)
    await moderation.reject(db_session, content=post, actor=admin, reason=None, now=NOW)

    later = NOW + timedelta(hours=1)
    await moderation.unhide(db_session, content=post, actor=other_admin, now=later)

    assert post.status == PUB
    assert post.hidden_reason is None
    assert post.published_at == later
    assert post.approved_by == other_admin.id
    assert post.approved_at == later
    assert author.trusted_at == later
    (row,) = await _audits(
        db_session, action="moderation.unhide", target_type="post", target_id=post.id
    )
    assert row.metadata_ == {"from": "hidden", "to": "published", "approved": True}
    (trust,) = await _audits(
        db_session, action="user.trusted", target_type="user", target_id=author.id
    )
    assert trust.actor_id == other_admin.id
    assert (
        await _audits(
            db_session, action="moderation.approve", target_type="post", target_id=post.id
        )
        == []
    )


@pytest.mark.parametrize("hidden_reason", [HiddenReason.ADMIN, HiddenReason.AUTO_REPORTS])
async def test_unhide_admin_or_auto_hidden_keeps_approval_fields(db_session, hidden_reason):
    first_admin = await create_admin(db_session)
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    approved_at = NOW - timedelta(days=3)
    post = await _make(
        db_session,
        ContentType.POST,
        PUB,
        author_id=author.id,
        approved_by=first_admin.id,
        approved_at=approved_at,
    )
    post.status = H
    post.hidden_reason = hidden_reason
    await db_session.flush()

    await moderation.unhide(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.approved_by == first_admin.id
    assert post.approved_at == approved_at
    assert author.trusted_at is None
    (row,) = await _audits(
        db_session, action="moderation.unhide", target_type="post", target_id=post.id
    )
    assert row.metadata_ == {"from": "hidden", "to": "published"}


# --- delete / restore -------------------------------------------------------------------------


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_delete_restore_published_round_trip_recounts_tags(db_session, content_type):
    admin = await create_admin(db_session)
    tag = await create_tag(db_session)
    content = await _make(db_session, content_type, PUB, tags=[tag])
    published_at = content.published_at
    await recount_tag_usage(db_session, tag_ids=[tag.id])
    assert await _usage(db_session, tag) == 1

    await moderation.delete(db_session, content=content, actor=admin, now=NOW)
    assert content.status == D
    assert content.deleted_at == NOW
    assert await _usage(db_session, tag) == 0

    await moderation.restore(db_session, content=content, actor=admin, now=NOW)
    assert content.status == PUB
    assert content.deleted_at is None
    assert content.published_at == published_at
    assert await _usage(db_session, tag) == 1


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_restore_never_approved_goes_back_to_pending(db_session, content_type):
    admin = await create_admin(db_session)
    tag = await create_tag(db_session)
    content = await _make(db_session, content_type, P, tags=[tag])

    await moderation.delete(db_session, content=content, actor=admin, now=NOW)
    await moderation.restore(db_session, content=content, actor=admin, now=NOW)

    assert content.status == P
    assert content.deleted_at is None
    assert await _usage(db_session, tag) == 0
    (row,) = await _audits(
        db_session,
        action="moderation.restore",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert row.metadata_ == {"from": "deleted", "to": "pending"}


async def test_restore_clears_hidden_reason(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, H)

    await moderation.delete(db_session, content=post, actor=admin, now=NOW)
    await moderation.restore(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.hidden_reason is None


async def test_hide_and_approve_recount_tags(db_session):
    admin = await create_admin(db_session)
    tag = await create_tag(db_session)
    post = await _make(db_session, ContentType.POST, P, tags=[tag])

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)
    assert await _usage(db_session, tag) == 1
    await moderation.hide(db_session, content=post, actor=admin, reason=None, now=NOW)
    assert await _usage(db_session, tag) == 0
    await moderation.unhide(db_session, content=post, actor=admin, now=NOW)
    assert await _usage(db_session, tag) == 1


# --- replies and comments ---------------------------------------------------------------------


@pytest.mark.parametrize("content_type", [ContentType.REPLY, ContentType.COMMENT])
async def test_reply_comment_hide_unhide_delete_restore(db_session, content_type):
    admin = await create_admin(db_session)
    content = await _make(db_session, content_type, PUB)
    parent = (
        await db_session.get(Thread, content.thread_id)
        if content_type == ContentType.REPLY
        else await db_session.get(Post, content.post_id)
    )
    counter = "reply_count" if content_type == ContentType.REPLY else "comment_count"

    async def count() -> int:
        await db_session.refresh(parent)
        return getattr(parent, counter)

    assert await count() == 1
    await moderation.hide(db_session, content=content, actor=admin, reason="rude", now=NOW)
    assert content.status == H
    assert await count() == 0
    await moderation.unhide(db_session, content=content, actor=admin, now=NOW)
    assert content.status == PUB
    assert await count() == 1
    await moderation.delete(db_session, content=content, actor=admin, now=NOW)
    assert content.status == D
    assert await count() == 0
    await moderation.restore(db_session, content=content, actor=admin, now=NOW)
    assert content.status == PUB
    assert await count() == 1

    actions = [
        row.action
        for row in await _audits(db_session, target_type=content_type.value, target_id=content.id)
    ]
    assert actions == [
        "moderation.hide",
        "moderation.unhide",
        "moderation.delete",
        "moderation.restore",
    ]


@pytest.mark.parametrize("content_type", [ContentType.REPLY, ContentType.COMMENT])
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_reply_comment_approve_reject_conflict(db_session, content_type, action):
    admin = await create_admin(db_session)
    content = await _make(db_session, content_type, PUB)

    with pytest.raises(AppError) as exc:
        await _call(action, db_session, content, admin)
    _assert_invalid(exc)
    assert content.status == PUB


# --- get_content ------------------------------------------------------------------------------


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_get_content_loads_author(db_session, content_type):
    author = await create_verified_user(db_session)
    content = await _make(db_session, content_type, H, author_id=author.id)
    db_session.expunge(content)

    loaded = await moderation.get_content(
        db_session, content_type=content_type, content_id=content.id
    )

    assert loaded is not None
    assert loaded.id == content.id
    assert loaded.status == H
    assert loaded.author.id == author.id


async def test_get_content_missing(db_session):
    assert (
        await moderation.get_content(db_session, content_type=ContentType.POST, content_id=0)
        is None
    )


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_get_content_out_of_range_id(db_session, content_type):
    """Ids past a column's range are simply not found (posts and threads have INTEGER ids;
    asking Postgres for 2**31 would fail with "integer out of range")."""
    too_big = moderation.MAX_INT_ID + 1 if content_type in moderation.REVIEWED_TYPES else 2**63 - 1
    assert (
        await moderation.get_content(
            db_session, content_type=content_type, content_id=too_big, for_update=True
        )
        is None
    )


async def test_open_reporter_count_is_public(db_session):
    reporter = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, PUB)
    await create_report(db_session, reporter_id=reporter.id, content_id=post.id)
    await create_report(db_session, reporter_id=None, content_id=post.id)
    assert (
        await moderation.open_reporter_count(
            db_session, content_type=ContentType.POST, content_id=post.id
        )
        == 1
    )


async def test_auto_hide_uses_given_reporter_count(db_session, monkeypatch):
    """``reporters`` given: no count query of its own (the caller just counted)."""
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 2)
    post = await _make(db_session, ContentType.POST, PUB)

    async def boom(*args, **kwargs):
        raise AssertionError("counted again")

    monkeypatch.setattr(moderation, "open_reporter_count", boom)
    assert (
        await moderation.auto_hide_if_reported(db_session, content=post, now=NOW, reporters=1)
        is False
    )
    assert (
        await moderation.auto_hide_if_reported(db_session, content=post, now=NOW, reporters=2)
        is True
    )
    assert post.status == H
    assert post.hidden_reason == HiddenReason.AUTO_REPORTS


# --- auto-hide --------------------------------------------------------------------------------


@pytest.fixture
def threshold(monkeypatch):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 3)


async def _reporters(db, n: int):
    return [await create_user(db) for _ in range(n)]


async def test_auto_hide_below_threshold(db_session, threshold):
    post = await _make(db_session, ContentType.POST, PUB)
    for reporter in await _reporters(db_session, 2):
        await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    assert await moderation.auto_hide_if_reported(db_session, content=post, now=NOW) is False
    assert post.status == PUB
    assert await _audits(db_session, target_type="post", target_id=post.id) == []


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_auto_hide_at_threshold(db_session, threshold, content_type):
    content = await _make(db_session, content_type, PUB)
    for reporter in await _reporters(db_session, 3):
        await create_report(
            db_session,
            reporter_id=reporter.id,
            content_type=content_type.value,
            content_id=content.id,
        )

    assert await moderation.auto_hide_if_reported(db_session, content=content, now=NOW) is True
    assert content.status == H
    assert content.hidden_reason == HiddenReason.AUTO_REPORTS
    (row,) = await _audits(
        db_session,
        action="moderation.auto_hidden",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert row.actor_id is None
    assert row.metadata_["from"] == "published"
    assert row.metadata_["to"] == "hidden"


async def test_auto_hide_same_reporter_counts_once(db_session, threshold):
    post = await _make(db_session, ContentType.POST, PUB)
    (reporter,) = await _reporters(db_session, 1)
    await create_report(db_session, reporter_id=reporter.id, content_id=post.id)
    for _ in range(2):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    assert await moderation.auto_hide_if_reported(db_session, content=post, now=NOW) is False
    assert post.status == PUB


async def test_auto_hide_ignores_closed_reports_and_other_content(db_session, threshold):
    post = await _make(db_session, ContentType.POST, PUB)
    a, b, c, d = await _reporters(db_session, 4)
    await create_report(db_session, reporter_id=a.id, content_id=post.id)
    await create_report(
        db_session, reporter_id=b.id, content_id=post.id, status=ReportStatus.DISMISSED
    )
    await create_report(
        db_session, reporter_id=c.id, content_id=post.id, status=ReportStatus.RESOLVED
    )
    await create_report(db_session, reporter_id=d.id, content_type="thread", content_id=post.id)

    assert await moderation.auto_hide_if_reported(db_session, content=post, now=NOW) is False
    assert post.status == PUB


async def test_auto_hide_only_published(db_session, threshold):
    post = await _make(db_session, ContentType.POST, P)
    for reporter in await _reporters(db_session, 3):
        await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    assert await moderation.auto_hide_if_reported(db_session, content=post, now=NOW) is False
    assert post.status == P


# --- pending queue ----------------------------------------------------------------------------


async def test_list_pending_mixes_posts_and_threads_oldest_first(db_session):
    total_before, _ = await moderation.list_pending(db_session, skip=0, limit=1)
    author = await create_verified_user(db_session)
    base = datetime(2000, 1, 1, tzinfo=UTC)  # older than anything else in the database
    t1 = await _make(db_session, ContentType.THREAD, P, author_id=author.id, created_at=base)
    p1 = await _make(
        db_session, ContentType.POST, P, author_id=author.id, created_at=base + timedelta(hours=1)
    )
    t2 = await _make(
        db_session, ContentType.THREAD, P, author_id=author.id, created_at=base + timedelta(hours=2)
    )
    # Not pending: never listed.
    await _make(db_session, ContentType.POST, PUB, created_at=base)
    await _make(db_session, ContentType.THREAD, H, created_at=base)

    total, items = await moderation.list_pending(db_session, skip=0, limit=2)
    assert total == total_before + 3
    assert [(ct, obj.id) for ct, obj in items] == [
        (ContentType.THREAD, t1.id),
        (ContentType.POST, p1.id),
    ]
    assert all(obj.author.id == author.id for _, obj in items)

    total, items = await moderation.list_pending(db_session, skip=2, limit=1)
    assert [(ct, obj.id) for ct, obj in items] == [(ContentType.THREAD, t2.id)]


# --- auto-approve sweep -----------------------------------------------------------------------


async def test_auto_approve_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 0)
    post = await _make(db_session, ContentType.POST, P, created_at=NOW - timedelta(days=30))

    assert await moderation.auto_approve_stale(db_session, now=NOW) == 0
    assert post.status == P


async def _stale_pending_count(db, cutoff: datetime) -> int:
    total = 0
    for model in (Post, Thread):
        stmt = select(func.count()).where(model.status == P, model.created_at < cutoff)
        total += (await db.execute(stmt)).scalar_one()
    return total


async def test_auto_approve_stale(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 2)
    author = await create_verified_user(db_session)
    other = await create_verified_user(db_session)
    old = await _make(
        db_session, ContentType.POST, P, author_id=author.id, created_at=NOW - timedelta(days=3)
    )
    fresh = await _make(
        db_session, ContentType.THREAD, P, author_id=other.id, created_at=NOW - timedelta(days=1)
    )
    expected = await _stale_pending_count(db_session, NOW - timedelta(days=2))
    assert expected >= 1

    assert await moderation.auto_approve_stale(db_session, now=NOW) == expected

    assert old.status == PUB
    assert old.approved_by is None
    assert old.approved_at == NOW
    assert old.published_at == NOW
    assert fresh.status == P
    assert author.trusted_at == NOW
    assert other.trusted_at is None
    (row,) = await _audits(
        db_session, action="moderation.auto_approved", target_type="post", target_id=old.id
    )
    assert row.actor_id is None
    assert row.metadata_ == {"from": "pending", "to": "published"}
    (trust,) = await _audits(
        db_session, action="user.trusted", target_type="user", target_id=author.id
    )
    assert trust.actor_id is None
    assert trust.metadata_["reason"] == "auto_approve"


# --- review fixes -----------------------------------------------------------------------------


async def test_auto_hide_threshold_zero_is_off(db_session, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 0)
    post = await _make(db_session, ContentType.POST, PUB)
    for reporter in await _reporters(db_session, 3):
        await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    assert await moderation.auto_hide_if_reported(db_session, content=post, now=NOW) is False
    assert post.status == PUB
    assert await _audits(db_session, target_type="post", target_id=post.id) == []


@pytest.mark.parametrize(
    "author_fields",
    [{"deleted_at": NOW - timedelta(days=1)}, {"is_active": False}],
    ids=["anonymised", "banned"],
)
async def test_approve_does_not_trust_dead_account(db_session, author_fields):
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session, **author_fields)
    post = await _make(db_session, ContentType.POST, P, author_id=author.id)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert author.trusted_at is None
    assert (
        await _audits(db_session, action="user.trusted", target_type="user", target_id=author.id)
        == []
    )


async def test_approve_trusts_through_set_trusted(db_session, monkeypatch):
    from app.crud import user as crud_user

    calls: list[dict] = []
    real = crud_user.set_trusted

    async def spy(db, **kwargs):
        calls.append(kwargs)
        return await real(db, **kwargs)

    monkeypatch.setattr(crud_user, "set_trusted", spy)
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, P, author_id=author.id)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert calls == [{"user": author, "trusted": True, "now": NOW}]
    assert author.trusted_at == NOW


async def test_restore_to_published_dismisses_open_reports(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, PUB)
    reports = [
        await create_report(db_session, reporter_id=reporter.id, content_id=post.id)
        for reporter in await _reporters(db_session, 3)
    ]
    post.status = H
    post.hidden_reason = HiddenReason.AUTO_REPORTS
    post.report_count = 3
    await db_session.flush()

    await moderation.delete(db_session, content=post, actor=admin, now=NOW)
    await moderation.restore(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.report_count == 0
    for report in reports:
        await db_session.refresh(report)
        assert report.status == ReportStatus.DISMISSED
        assert report.resolved_by == admin.id
        assert report.resolved_at == NOW


async def test_get_content_for_update_locks_row(db_session):
    from sqlalchemy import event

    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, PUB, author_id=author.id)
    statements: list[str] = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        loaded = await moderation.get_content(
            db_session, content_type=ContentType.POST, content_id=post.id, for_update=True
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert loaded is not None
    assert loaded.author.id == author.id
    assert any("FOR UPDATE OF posts" in sql for sql in statements), statements


# --- 5o: rejection note and resubmission ------------------------------------------------------


async def _rejected(db, content_type: ContentType = ContentType.POST, *, reason="Too vague"):
    """A post/thread rejected by an admin with ``reason``; returns ``(author, content)``."""
    admin = await create_admin(db)
    author = await create_verified_user(db)
    content = await _make(db, content_type, P, author_id=author.id)
    await moderation.reject(db, content=content, actor=admin, reason=reason, now=NOW)
    return author, content


def test_note_max_length_matches_the_reason_schema():
    from app.api.v1.schemas.moderation import REASON_MAX_LENGTH

    assert moderation.NOTE_MAX_LENGTH == REASON_MAX_LENGTH


@pytest.mark.parametrize("table", ["posts", "threads"])
async def test_moderation_note_column_on_posts_and_threads(db_session, table):
    from sqlalchemy import text

    row = (
        await db_session.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = 'moderation_note'"
            ),
            {"table": table},
        )
    ).one()
    assert row.data_type == "text"
    assert row.is_nullable == "YES"


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_reject_stores_the_reason_as_note(db_session, content_type):
    _, content = await _rejected(db_session, content_type, reason="Please add sources.")

    await db_session.refresh(content)
    assert content.moderation_note == "Please add sources."


async def test_reject_note_is_plain_text_trimmed_and_capped(db_session):
    reason = "  Line one\r\nLine two\x00\x07 " + "x" * 600
    _, post = await _rejected(db_session, reason=reason)

    assert post.moderation_note is not None
    assert post.moderation_note.startswith("Line one\nLine two")
    assert "\x00" not in post.moderation_note
    assert "\x07" not in post.moderation_note
    assert "\r" not in post.moderation_note
    assert len(post.moderation_note) == moderation.NOTE_MAX_LENGTH


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_reject_without_reason_stores_no_note(db_session, reason):
    _, post = await _rejected(db_session, reason=reason)

    assert post.moderation_note is None


async def test_approve_clears_the_note(db_session):
    admin = await create_admin(db_session)
    author, post = await _rejected(db_session)
    await moderation.resubmit(db_session, content=post, actor=author, now=NOW)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert post.status == PUB
    assert post.moderation_note is None


async def test_unhide_rejected_clears_the_note(db_session):
    admin = await create_admin(db_session)
    _, post = await _rejected(db_session)

    await moderation.unhide(db_session, content=post, actor=admin, now=NOW)

    assert post.moderation_note is None


async def test_auto_approve_clears_the_note(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 2)
    author, thread = await _rejected(db_session, ContentType.THREAD)
    thread.created_at = NOW - timedelta(days=3)
    await moderation.resubmit(db_session, content=thread, actor=author, now=NOW)

    await moderation.auto_approve_stale(db_session, now=NOW)

    assert thread.status == PUB
    assert thread.moderation_note is None


async def test_hide_with_reason_does_not_store_a_note(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, PUB)

    await moderation.hide(db_session, content=post, actor=admin, reason="Spam links", now=NOW)

    assert post.moderation_note is None
    (row,) = await _audits(
        db_session, action="moderation.hide", target_type="post", target_id=post.id
    )
    assert row.metadata_["reason"] == "Spam links"


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_resubmit_rejected_goes_back_to_pending(db_session, content_type):
    author, content = await _rejected(db_session, content_type, reason="Add a map.")

    result = await moderation.resubmit(db_session, content=content, actor=author, now=NOW)

    assert result is content
    assert content.status == P
    assert content.hidden_reason is None
    assert content.moderation_note == "Add a map."
    assert content.published_at is None
    assert author.trusted_at is None
    (row,) = await _audits(
        db_session,
        action="moderation.resubmit",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert row.actor_id == author.id
    assert row.metadata_ == {"from": "hidden", "to": "pending"}
    assert (
        await _audits(db_session, action="user.trusted", target_type="user", target_id=author.id)
        == []
    )


@pytest.mark.parametrize("start", [P, PUB, D])
async def test_resubmit_needs_a_rejected_item(db_session, start):
    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, start, author_id=author.id)

    with pytest.raises(AppError) as exc:
        await moderation.resubmit(db_session, content=post, actor=author, now=NOW)

    _assert_invalid(exc)
    assert post.status == start


@pytest.mark.parametrize("hidden_reason", [HiddenReason.ADMIN, HiddenReason.AUTO_REPORTS])
async def test_resubmit_hidden_by_admin_or_reports_is_invalid(db_session, hidden_reason):
    author = await create_verified_user(db_session)
    thread = await _make(db_session, ContentType.THREAD, H, author_id=author.id)
    thread.hidden_reason = hidden_reason

    with pytest.raises(AppError) as exc:
        await moderation.resubmit(db_session, content=thread, actor=author, now=NOW)

    _assert_invalid(exc)
    assert thread.status == H


@pytest.mark.parametrize("content_type", [ContentType.REPLY, ContentType.COMMENT])
async def test_resubmit_reply_or_comment_is_invalid(db_session, content_type):
    author = await create_verified_user(db_session)
    content = await _make(db_session, content_type, H, author_id=author.id)
    content.hidden_reason = HiddenReason.REJECTED

    with pytest.raises(AppError) as exc:
        await moderation.resubmit(db_session, content=content, actor=author, now=NOW)

    _assert_invalid(exc)


async def test_resubmit_twice_is_invalid(db_session):
    author, post = await _rejected(db_session)
    await moderation.resubmit(db_session, content=post, actor=author, now=NOW)

    with pytest.raises(AppError) as exc:
        await moderation.resubmit(db_session, content=post, actor=author, now=NOW)

    _assert_invalid(exc)


async def test_reject_after_resubmit_replaces_the_note(db_session):
    admin = await create_admin(db_session)
    author, post = await _rejected(db_session, reason="First note")
    await moderation.resubmit(db_session, content=post, actor=author, now=NOW)

    await moderation.reject(db_session, content=post, actor=admin, reason="Second note", now=NOW)

    assert post.moderation_note == "Second note"
