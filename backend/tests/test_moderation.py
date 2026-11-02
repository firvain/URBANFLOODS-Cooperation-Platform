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
from app.db.models import AuditLog, Post, Tag, Thread, User
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


async def test_restore_of_a_never_hidden_item_has_no_hidden_reason(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, PUB)

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
    """Posts and threads the sweep should approve: stale, pending, never rejected, by a live
    (active, not erased) author."""
    total = 0
    for model in (Post, Thread):
        stmt = (
            select(func.count())
            .select_from(model)
            .join(User, User.id == model.author_id)
            .where(
                model.status == P,
                model.created_at < cutoff,
                model.rejected_at.is_(None),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
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
        for reporter in await _reporters(db_session, 2)
    ]
    post.report_count = 2
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


async def test_auto_approve_leaves_a_resubmitted_item_and_its_note(db_session, monkeypatch):
    """7i (2b): a resubmitted item always waits for an admin, so its note stays (it used to be
    auto-approved, and its note cleared, on the next sweep)."""
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 2)
    author, thread = await _rejected(db_session, ContentType.THREAD)
    thread.created_at = NOW - timedelta(days=3)
    await moderation.resubmit(db_session, content=thread, actor=author, now=NOW)

    await moderation.auto_approve_stale(db_session, now=NOW)

    assert thread.status == P
    assert thread.moderation_note == "Too vague"


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


# --- 7i: auto-approve sweep fixes -------------------------------------------------------------

STALE = NOW - timedelta(days=30)


@pytest.fixture
def auto_approve_days(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 2)


async def _approved_audits(db, content) -> list:
    return await _audits(
        db,
        action="moderation.auto_approved",
        target_type=moderation.content_type_of(content).value,
        target_id=content.id,
    )


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
@pytest.mark.parametrize(
    "author_fields",
    [{"is_active": False}, {"deleted_at": NOW - timedelta(days=1)}],
    ids=["banned", "erased"],
)
async def test_auto_approve_skips_dead_accounts(
    db_session, auto_approve_days, content_type, author_fields
):
    """2a: a stale pending item of a banned or erased author stays pending for an admin."""
    author = await create_verified_user(db_session, **author_fields)
    content = await _make(db_session, content_type, P, author_id=author.id, created_at=STALE)
    approved: list[moderation.ApprovedItem] = []

    count = await moderation.auto_approve_stale(db_session, now=NOW, approved=approved)

    assert count == 0
    assert approved == []
    await db_session.refresh(content)
    assert content.status == P
    assert content.published_at is None
    assert content.approved_at is None
    assert await _approved_audits(db_session, content) == []
    await db_session.refresh(author)
    assert author.trusted_at is None


async def test_auto_approve_skips_an_anonymised_author(db_session, auto_approve_days):
    """2a, through the real GDPR erasure helper."""
    from app.crud import user as crud_user

    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, P, author_id=author.id, created_at=STALE)
    await crud_user.anonymise_user(db_session, user=author, now=NOW - timedelta(days=1))

    assert await moderation.auto_approve_stale(db_session, now=NOW) == 0

    await db_session.refresh(post)
    assert post.status == P
    assert await _approved_audits(db_session, post) == []


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_auto_approve_skips_items_without_author(db_session, auto_approve_days, content_type):
    """2a: no author, no auto-approval."""
    content = await _make(db_session, content_type, P, author_id=None, created_at=STALE)

    assert await moderation.auto_approve_stale(db_session, now=NOW) == 0

    await db_session.refresh(content)
    assert content.status == P
    assert await _approved_audits(db_session, content) == []


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
@pytest.mark.parametrize("reason", ["Add a map.", None])
async def test_reject_sets_rejected_at_and_resubmit_keeps_it(db_session, content_type, reason):
    """2b: ``rejected_at`` is set by reject (with or without a reason) and kept by resubmit."""
    author, content = await _rejected(db_session, content_type, reason=reason)

    assert content.rejected_at == NOW

    later = NOW + timedelta(hours=1)
    await moderation.resubmit(db_session, content=content, actor=author, now=later)

    assert content.status == P
    assert content.rejected_at == NOW


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
@pytest.mark.parametrize("reason", ["Add a map.", None])
async def test_auto_approve_never_approves_a_resubmitted_item(
    db_session, auto_approve_days, content_type, reason
):
    """2b: a rejected and resubmitted item needs an admin however long it waits; its author is
    not trusted by the sweep."""
    author = await create_verified_user(db_session)
    admin = await create_admin(db_session)
    content = await _make(db_session, content_type, P, author_id=author.id, created_at=STALE)
    await moderation.reject(db_session, content=content, actor=admin, reason=reason, now=NOW)
    await moderation.resubmit(db_session, content=content, actor=author, now=NOW)

    much_later = NOW + timedelta(days=365)
    assert await moderation.auto_approve_stale(db_session, now=much_later) == 0

    await db_session.refresh(content)
    assert content.status == P
    assert content.rejected_at == NOW
    assert await _approved_audits(db_session, content) == []
    await db_session.refresh(author)
    assert author.trusted_at is None


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_approve_clears_rejected_at(db_session, content_type):
    admin = await create_admin(db_session)
    author, content = await _rejected(db_session, content_type, reason=None)
    await moderation.resubmit(db_session, content=content, actor=author, now=NOW)

    await moderation.approve(db_session, content=content, actor=admin, now=NOW)

    assert content.status == PUB
    assert content.rejected_at is None


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_unhide_rejected_clears_rejected_at(db_session, content_type):
    admin = await create_admin(db_session)
    _, content = await _rejected(db_session, content_type)

    await moderation.unhide(db_session, content=content, actor=admin, now=NOW)

    assert content.status == PUB
    assert content.rejected_at is None


async def test_approve_never_rejected_leaves_rejected_at_empty(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, P)

    await moderation.approve(db_session, content=post, actor=admin, now=NOW)

    assert post.rejected_at is None


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_restore_of_a_rejected_never_approved_item_keeps_rejected_at(
    db_session, auto_approve_days, content_type
):
    """A rejected item that was deleted and restored goes back to ``hidden(rejected)`` (7j), still
    marked rejected; once its author resubmits it, the sweep leaves it for an admin."""
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    content = await _make(db_session, content_type, P, author_id=author.id, created_at=STALE)
    await moderation.reject(db_session, content=content, actor=admin, reason="Vague", now=NOW)
    await moderation.delete(db_session, content=content, actor=admin, now=NOW)

    await moderation.restore(db_session, content=content, actor=admin, now=NOW)

    assert content.status == H
    assert content.hidden_reason == HiddenReason.REJECTED
    assert content.rejected_at == NOW
    assert content.moderation_note == "Vague"
    await moderation.resubmit(db_session, content=content, actor=author, now=NOW)
    assert content.status == P
    assert await moderation.auto_approve_stale(db_session, now=NOW + timedelta(days=30)) == 0
    await db_session.refresh(content)
    assert content.status == P
    assert await _approved_audits(db_session, content) == []


@pytest.mark.parametrize("table", ["posts", "threads"])
async def test_rejected_at_column_on_posts_and_threads(db_session, table):
    from sqlalchemy import text

    row = (
        await db_session.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = 'rejected_at'"
            ),
            {"table": table},
        )
    ).one()
    assert row.data_type == "timestamp with time zone"
    assert row.is_nullable == "YES"


async def test_auto_approve_still_approves_a_live_authors_stale_item(db_session, auto_approve_days):
    """The fixes leave the normal case alone: a stale, never-rejected item of an active author is
    approved and reported in ``approved``."""
    author = await create_verified_user(db_session)
    thread = await _make(db_session, ContentType.THREAD, P, author_id=author.id, created_at=STALE)
    approved: list[moderation.ApprovedItem] = []

    await moderation.auto_approve_stale(db_session, now=NOW, approved=approved)

    assert thread.status == PUB
    assert moderation.ApprovedItem(ContentType.THREAD, thread.id, True) in approved
    assert author.trusted_at == NOW


# --- 7i: the sweep against concurrent transactions ----------------------------------------------
#
# These tests commit their rows (users through ``cleanup_users``, content through categories in
# ``cleanup_forum_categories``, which removes threads and posts) so that a second connection, the
# "admin" transaction, can see and lock them. The sweep runs on ``db_session`` with a short
# ``lock_timeout``: a sweep that waits for a lock fails with an error instead of hanging. The
# sweep itself is never committed (``db_session`` is rolled back before the cleanup runs).

SWEEP_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '2s'"


@pytest.fixture
async def committed_stale(db_session, cleanup_users, cleanup_forum_categories):
    """``make(content_type)`` commits a verified author and a stale pending post/thread of theirs
    and returns ``(author, content)``. Rolls ``db_session`` back before the cleanup."""

    async def make(content_type: ContentType):
        author = await create_verified_user(db_session)
        cleanup_users.add(author.email)
        kind = CategoryKind.BLOG if content_type == ContentType.POST else CategoryKind.FORUM
        category = await create_category(db_session, kind=kind)
        cleanup_forum_categories.add(category.id)
        factory = create_post if content_type == ContentType.POST else create_thread
        content = await factory(
            db_session,
            category_id=category.id,
            status=P,
            author_id=author.id,
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        await db_session.commit()
        return author, content

    yield make
    await db_session.rollback()


@pytest.fixture
async def admin_tx():
    """A second connection with an open transaction (an admin's request in flight)."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def _sweep(db, approved: list[moderation.ApprovedItem]) -> int:
    from sqlalchemy import text

    await db.execute(text(SWEEP_LOCK_TIMEOUT))
    return await moderation.auto_approve_stale(db, approved=approved)


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
@pytest.mark.parametrize("in_flight", ["reject", "ban"])
async def test_auto_approve_skips_rows_locked_by_an_admin_and_the_decision_wins(
    db_session, auto_approve_days, committed_stale, admin_tx, content_type, in_flight
):
    """2d: while an admin's reject (content row) or ban (author row) is uncommitted, the sweep
    neither waits nor approves the item (``SKIP LOCKED`` on both rows); once it commits, the next
    sweep sees the decision and leaves the item alone."""
    from sqlalchemy import update

    author, content = await committed_stale(content_type)
    model = type(content)
    if in_flight == "reject":
        await admin_tx.execute(
            update(model)
            .where(model.id == content.id)
            .values(status=H, hidden_reason=HiddenReason.REJECTED, rejected_at=NOW)
        )
    else:
        await admin_tx.execute(update(User).where(User.id == author.id).values(is_active=False))

    approved: list[moderation.ApprovedItem] = []
    await _sweep(db_session, approved)

    ours = (content_type, content.id)
    assert ours not in [(i.content_type, i.content_id) for i in approved]
    await admin_tx.commit()

    await _sweep(db_session, approved)

    assert ours not in [(i.content_type, i.content_id) for i in approved]
    await db_session.refresh(content)
    assert content.status == (H if in_flight == "reject" else P)
    assert content.approved_at is None
    await db_session.refresh(author)
    assert author.trusted_at is None
    assert await _approved_audits(db_session, content) == []


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_auto_approve_trusts_the_fresh_author_row(
    db_session, auto_approve_days, committed_stale, admin_tx, content_type
):
    """The author is re-read by the sweep's locking query (not taken stale from the session):
    trusted meanwhile by another transaction, they are not trusted (or audited) a second time."""
    from sqlalchemy import update

    author, content = await committed_stale(content_type)
    # Load every column into the session's copy (a fresh factory object leaves some unloaded,
    # which any query would fill in): it is about to go stale.
    await db_session.refresh(author)
    await db_session.commit()
    assert author.trusted_at is None
    trusted_at = datetime.now(UTC) - timedelta(hours=1)
    await admin_tx.execute(update(User).where(User.id == author.id).values(trusted_at=trusted_at))
    await admin_tx.commit()

    approved: list[moderation.ApprovedItem] = []
    await _sweep(db_session, approved)

    assert moderation.ApprovedItem(content_type, content.id, False) in approved
    assert author.trusted_at == trusted_at
    assert (
        await _audits(db_session, action="user.trusted", target_type="user", target_id=author.id)
        == []
    )


async def test_auto_approve_locks_content_and_author_rows_skipping_locked(
    db_session, auto_approve_days
):
    """The sweep's select locks both rows and skips the locked ones, for posts and threads."""
    from sqlalchemy import event

    statements: list[str] = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        await moderation.auto_approve_stale(db_session, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    for table in ("posts", "threads"):
        assert any(f"FOR UPDATE OF {table}, users SKIP LOCKED" in sql for sql in statements), (
            statements
        )


# --- 7j: restore keeps hidden content hidden; dismissed reports are audited ---------------------

HIDDEN_CASES = [
    (ContentType.POST, HiddenReason.ADMIN),
    (ContentType.POST, HiddenReason.AUTO_REPORTS),
    (ContentType.POST, HiddenReason.REJECTED),
    (ContentType.THREAD, HiddenReason.ADMIN),
    (ContentType.THREAD, HiddenReason.AUTO_REPORTS),
    (ContentType.THREAD, HiddenReason.REJECTED),
    (ContentType.REPLY, HiddenReason.ADMIN),
    (ContentType.REPLY, HiddenReason.AUTO_REPORTS),
    (ContentType.COMMENT, HiddenReason.ADMIN),
    (ContentType.COMMENT, HiddenReason.AUTO_REPORTS),
]


async def _hidden_with_reports(db, content_type: ContentType, reason: HiddenReason):
    """Hidden content (``reason``) with two open reports; a rejected post/thread was never
    published and carries ``rejected_at`` and a note."""
    content = await _make(db, content_type, H)
    content.hidden_reason = reason
    if reason == HiddenReason.REJECTED:
        content.published_at = None
        content.rejected_at = NOW - timedelta(days=3)
        content.moderation_note = "Add a source."
    reports = [
        await create_report(
            db, reporter_id=reporter.id, content_type=content_type.value, content_id=content.id
        )
        for reporter in await _reporters(db, 2)
    ]
    content.report_count = 2
    await db.flush()
    return content, reports


@pytest.mark.parametrize(("content_type", "reason"), HIDDEN_CASES)
async def test_restore_of_a_hidden_item_goes_back_to_hidden(db_session, content_type, reason):
    admin = await create_admin(db_session)
    content, reports = await _hidden_with_reports(db_session, content_type, reason)
    published_at = getattr(content, "published_at", None)
    rejected_at = getattr(content, "rejected_at", None)

    await moderation.delete(db_session, content=content, actor=admin, now=NOW)
    assert content.hidden_reason == reason
    await moderation.restore(db_session, content=content, actor=admin, now=NOW)

    await db_session.refresh(content)
    assert content.status == H
    assert content.hidden_reason == reason
    assert content.deleted_at is None
    assert content.report_count == 2
    assert getattr(content, "published_at", None) == published_at
    assert getattr(content, "rejected_at", None) == rejected_at
    if reason == HiddenReason.REJECTED:
        assert content.moderation_note == "Add a source."
    for report in reports:
        await db_session.refresh(report)
        assert report.status == ReportStatus.OPEN
        assert report.resolved_by is None
    (row,) = await _audits(
        db_session,
        action="moderation.restore",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert row.actor_id == admin.id
    assert row.metadata_ == {"from": "deleted", "to": "hidden", "hidden_reason": reason.value}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "report.dismiss",
                AuditLog.target_type == "report",
                AuditLog.target_id.in_([r.id for r in reports]),
            )
        )
        == 0
    )


async def test_restore_of_a_hidden_item_keeps_tags_uncounted(db_session):
    admin = await create_admin(db_session)
    tag = await create_tag(db_session)
    post = await _make(db_session, ContentType.POST, H, tags=[tag])
    await recount_tag_usage(db_session, tag_ids=[tag.id])

    await moderation.delete(db_session, content=post, actor=admin, now=NOW)
    await moderation.restore(db_session, content=post, actor=admin, now=NOW)

    assert post.status == H
    assert await _usage(db_session, tag) == 0


async def test_author_deleted_hidden_post_restores_to_hidden(db_session):
    """The author's own soft delete keeps ``hidden_reason``, so an admin's restore cannot
    republish content that was taken down."""
    from app.crud.post import soft_delete_post

    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    post = await _make(db_session, ContentType.POST, H, author_id=author.id)
    await db_session.refresh(post, ["tags"])

    await soft_delete_post(db_session, post=post, now=NOW)
    assert post.hidden_reason == HiddenReason.ADMIN
    await moderation.restore(db_session, content=post, actor=admin, now=NOW)

    assert post.status == H
    assert post.hidden_reason == HiddenReason.ADMIN


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_own_soft_delete_keeps_hidden_reason(db_session, content_type):
    from app.crud.comment import soft_delete_comment
    from app.crud.post import soft_delete_post
    from app.crud.reply import soft_delete_reply
    from app.crud.thread import soft_delete_thread

    content = await _make(db_session, content_type, H)
    if content_type in (ContentType.POST, ContentType.THREAD):
        await db_session.refresh(content, ["tags"])
    soft_delete = {
        ContentType.POST: lambda: soft_delete_post(db_session, post=content, now=NOW),
        ContentType.THREAD: lambda: soft_delete_thread(db_session, thread=content, now=NOW),
        ContentType.REPLY: lambda: soft_delete_reply(db_session, reply=content, now=NOW),
        ContentType.COMMENT: lambda: soft_delete_comment(db_session, comment=content, now=NOW),
    }[content_type]

    await soft_delete()

    await db_session.refresh(content)
    assert content.status == D
    assert content.hidden_reason == HiddenReason.ADMIN


async def _dismiss_audits(db, report_ids: list[int]) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.action == "report.dismiss",
            AuditLog.target_type == "report",
            AuditLog.target_id.in_(report_ids),
        )
        .order_by(AuditLog.target_id)
    )
    return list((await db.scalars(stmt)).all())


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_unhide_audits_each_dismissed_report(db_session, content_type):
    admin = await create_admin(db_session)
    content, reports = await _hidden_with_reports(db_session, content_type, HiddenReason.ADMIN)
    (other,) = await _reporters(db_session, 1)
    closed = await create_report(
        db_session,
        reporter_id=other.id,
        content_type=content_type.value,
        content_id=content.id,
        status=ReportStatus.RESOLVED,
    )

    await moderation.unhide(db_session, content=content, actor=admin, now=NOW)

    rows = await _dismiss_audits(db_session, [r.id for r in reports] + [closed.id])
    assert [row.target_id for row in rows] == sorted(r.id for r in reports)
    for row in rows:
        assert row.actor_id == admin.id
        assert row.metadata_ == {
            "content_type": content_type.value,
            "content_id": content.id,
            "via": "unhide",
        }


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_restore_to_published_audits_each_dismissed_report(db_session, content_type):
    admin = await create_admin(db_session)
    content = await _make(db_session, content_type, PUB)
    reports = [
        await create_report(
            db_session,
            reporter_id=reporter.id,
            content_type=content_type.value,
            content_id=content.id,
        )
        for reporter in await _reporters(db_session, 2)
    ]
    await moderation.delete(db_session, content=content, actor=admin, now=NOW)

    await moderation.restore(db_session, content=content, actor=admin, now=NOW)

    assert content.status == PUB
    rows = await _dismiss_audits(db_session, [r.id for r in reports])
    assert [row.target_id for row in rows] == sorted(r.id for r in reports)
    for row in rows:
        assert row.actor_id == admin.id
        assert row.metadata_ == {
            "content_type": content_type.value,
            "content_id": content.id,
            "via": "restore",
        }


async def test_unhide_without_open_reports_writes_no_dismiss_audit(db_session):
    admin = await create_admin(db_session)
    post = await _make(db_session, ContentType.POST, H)

    await moderation.unhide(db_session, content=post, actor=admin, now=NOW)

    rows = await _audits(db_session, target_type="post", target_id=post.id)
    assert [row.action for row in rows] == ["moderation.unhide"]


# --- 7j: the queue survives an item that vanished between its two queries ----------------------


async def test_list_pending_skips_a_row_purged_between_page_and_load(db_session, monkeypatch):
    """A purge committed between the page read and the row load must not turn into a KeyError
    (a 500 on the queue and in the admin digest): the vanished row is skipped."""
    from sqlalchemy import delete as sql_delete

    author = await create_verified_user(db_session)
    base = datetime(2000, 1, 1, tzinfo=UTC)  # first in the (global) oldest-first queue
    gone = await _make(db_session, ContentType.POST, P, author_id=author.id, created_at=base)
    kept = await _make(
        db_session,
        ContentType.THREAD,
        P,
        author_id=author.id,
        created_at=base + timedelta(hours=1),
    )
    gone_id = gone.id
    real_execute = db_session.execute
    calls = 0

    async def execute(statement, *args, **kwargs):
        nonlocal calls
        result = await real_execute(statement, *args, **kwargs)
        calls += 1
        if calls == 2:  # the page read: the post vanishes right after it
            await real_execute(
                sql_delete(Post)
                .where(Post.id == gone_id)
                .execution_options(synchronize_session=False)
            )
        return result

    monkeypatch.setattr(db_session, "execute", execute)
    db_session.expunge(gone)

    total, items = await moderation.list_pending(db_session, skip=0, limit=2)

    assert calls >= 2
    assert [(ct, obj.id) for ct, obj in items] == [(ContentType.THREAD, kept.id)]
    assert total >= 1
