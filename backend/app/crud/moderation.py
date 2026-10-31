"""Content moderation: the single place where a post, thread, reply or comment changes status
(besides the author's own soft delete in the content modules). Never commits; the caller does.

State machine (docs/PLAN.md, "State machines"), enforced by :data:`TRANSITIONS`:

- ``pending`` → approve → ``published``; ``pending`` → reject → ``hidden(rejected)``
- ``published`` → hide → ``hidden(admin)`` (or ``hidden(auto_reports)`` via
  :func:`auto_hide_if_reported`)
- ``hidden`` → unhide → ``published`` (an approval when it was ``hidden(rejected)``)
- any non-deleted → delete → ``deleted``
- ``deleted`` → restore → ``published``, or ``pending`` if it was never approved

Replies and comments have no ``pending`` state, so approve/reject on them is always invalid. Any
other edge raises 409 ``moderation.invalid_transition``. Every transition writes an
``moderation.<action>`` audit row with ``{"from", "to", "reason"?}``. Approving a member's
content marks them trusted (``user.trusted`` audit row). Tag usage counts only published posts
and threads, so every post/thread transition refreshes them; the reply/comment counters on
threads and posts are kept by database triggers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, literal, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import user as crud_user
from app.crud.audit import log_action
from app.crud.tag import recount_tag_usage
from app.db.enums import ContentStatus, ContentType, HiddenReason, ReportStatus
from app.db.models import Comment, Post, Reply, Report, Thread, User, post_tags, thread_tags

ContentModel = Post | Thread | Reply | Comment

MODELS: dict[ContentType, type[Any]] = {
    ContentType.POST: Post,
    ContentType.THREAD: Thread,
    ContentType.REPLY: Reply,
    ContentType.COMMENT: Comment,
}
_TYPES: dict[type[Any], ContentType] = {model: ct for ct, model in MODELS.items()}
# Only posts and threads go through review.
REVIEWED_TYPES = frozenset({ContentType.POST, ContentType.THREAD})

_P = ContentStatus.PENDING
_PUB = ContentStatus.PUBLISHED
_H = ContentStatus.HIDDEN
_D = ContentStatus.DELETED

# action -> {from status: to status}. ``restore`` lands on ``pending`` instead when the content
# was never approved (no ``published_at``).
TRANSITIONS: dict[str, dict[ContentStatus, ContentStatus]] = {
    "approve": {_P: _PUB},
    "reject": {_P: _H},
    "hide": {_PUB: _H},
    "unhide": {_H: _PUB},
    "delete": {_P: _D, _PUB: _D, _H: _D},
    "restore": {_D: _PUB},
}
_REVIEW_ACTIONS = frozenset({"approve", "reject"})


def invalid_transition(action: str, status: ContentStatus) -> AppError:
    return AppError(
        409,
        "moderation.invalid_transition",
        f"Cannot {action} content that is {status.value}.",
    )


def content_type_of(content: ContentModel) -> ContentType:
    return _TYPES[type(content)]


# --- reads ------------------------------------------------------------------------------------


async def get_content(
    db: AsyncSession, *, content_type: ContentType, content_id: int, for_update: bool = False
) -> ContentModel | None:
    """The content item (any status) with its author loaded, refreshed from the database.

    ``for_update`` locks the content row (only that row: Postgres refuses ``FOR UPDATE`` on the
    nullable side of the author outer join, hence ``of=``) until the transaction ends.
    """
    model = MODELS[content_type]
    stmt = (
        select(model)
        .where(model.id == content_id)
        .options(joinedload(model.author))
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=model)
    return (await db.scalars(stmt)).unique().one_or_none()


async def list_pending(
    db: AsyncSession, *, skip: int = 0, limit: int = 50
) -> tuple[int, list[tuple[ContentType, Post | Thread]]]:
    """``(total, [(content_type, obj), ...])`` of pending posts and threads, oldest first, each
    with its author loaded."""
    queue = union_all(
        select(
            literal(ContentType.POST.value).label("content_type"),
            Post.id.label("id"),
            Post.created_at.label("created_at"),
        ).where(Post.status == _P),
        select(
            literal(ContentType.THREAD.value).label("content_type"),
            Thread.id.label("id"),
            Thread.created_at.label("created_at"),
        ).where(Thread.status == _P),
    ).subquery()
    total = (await db.execute(select(func.count()).select_from(queue))).scalar_one()
    page = (
        await db.execute(
            select(queue.c.content_type, queue.c.id)
            .order_by(queue.c.created_at.asc(), queue.c.content_type, queue.c.id)
            .offset(skip)
            .limit(limit)
        )
    ).all()

    loaded: dict[tuple[ContentType, int], Post | Thread] = {}
    for content_type in REVIEWED_TYPES:
        model = MODELS[content_type]
        ids = [row.id for row in page if row.content_type == content_type.value]
        if not ids:
            continue
        rows = await db.scalars(
            select(model).where(model.id.in_(ids)).options(joinedload(model.author))
        )
        for obj in rows.unique():
            loaded[(content_type, obj.id)] = obj
    items = [
        (ContentType(row.content_type), loaded[(ContentType(row.content_type), row.id)])
        for row in page
    ]
    return total, items


async def _open_reporter_count(
    db: AsyncSession, *, content_type: ContentType, content_id: int
) -> int:
    stmt = select(func.count(func.distinct(Report.reporter_id))).where(
        Report.content_type == content_type,
        Report.content_id == content_id,
        Report.status == ReportStatus.OPEN,
    )
    return (await db.execute(stmt)).scalar_one()


# --- internals --------------------------------------------------------------------------------


def _target(content: ContentModel, action: str) -> ContentStatus:
    """The status ``action`` moves ``content`` to; 409 when the edge does not exist."""
    content_type = content_type_of(content)
    status = content.status
    if action in _REVIEW_ACTIONS and content_type not in REVIEWED_TYPES:
        raise invalid_transition(action, status)
    to = TRANSITIONS[action].get(status)
    if to is None:
        raise invalid_transition(action, status)
    if action == "restore" and content_type in REVIEWED_TYPES and content.published_at is None:
        return _P
    return to


async def _recount_tags(db: AsyncSession, content: ContentModel) -> None:
    if isinstance(content, Post):
        stmt = select(post_tags.c.tag_id).where(post_tags.c.post_id == content.id)
    elif isinstance(content, Thread):
        stmt = select(thread_tags.c.tag_id).where(thread_tags.c.thread_id == content.id)
    else:
        return
    await recount_tag_usage(db, tag_ids=(await db.scalars(stmt)).all())


async def _finish(
    db: AsyncSession,
    *,
    content: ContentModel,
    from_status: ContentStatus,
    audit_action: str,
    actor: User | None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ContentModel:
    """Flush the change, refresh tag counts and write the audit row."""
    await db.flush()
    await _recount_tags(db, content)
    metadata: dict[str, Any] = {"from": from_status.value, "to": content.status.value}
    if reason is not None:
        metadata["reason"] = reason
    if extra:
        metadata.update(extra)
    await log_action(
        db,
        actor_id=actor.id if actor is not None else None,
        action=audit_action,
        target_type=content_type_of(content).value,
        target_id=content.id,
        metadata=metadata,
    )
    return content


async def _dismiss_open_reports(
    db: AsyncSession, *, content: ContentModel, actor: User | None, now: datetime
) -> None:
    """Dismiss every open report on ``content`` and reset its ``report_count``."""
    await db.execute(
        update(Report)
        .where(
            Report.content_type == content_type_of(content),
            Report.content_id == content.id,
            Report.status == ReportStatus.OPEN,
        )
        .values(
            status=ReportStatus.DISMISSED,
            resolved_by=actor.id if actor is not None else None,
            resolved_at=now,
        )
        .execution_options(synchronize_session="fetch")
    )
    content.report_count = 0


async def _trust_author(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User | None,
    reason: str,
    now: datetime,
) -> None:
    """Mark the author trusted and audit it, unless they already are trusted or the account is
    gone (no author, anonymised or banned: trusting it would undo ``anonymise_user``)."""
    if content.author_id is None:
        return
    author = await db.get(User, content.author_id)
    if author is None or author.deleted_at is not None or not author.is_active:
        return
    if not await crud_user.set_trusted(db, user=author, trusted=True, now=now):
        return
    await log_action(
        db,
        actor_id=actor.id if actor is not None else None,
        action="user.trusted",
        target_type="user",
        target_id=author.id,
        metadata={
            "reason": reason,
            "content_type": content_type_of(content).value,
            "content_id": content.id,
        },
    )


def _set_approval(content: ContentModel, *, actor: User | None, now: datetime) -> None:
    """The approval fields of a post/thread; ``published_at`` only if it was never set."""
    if content.published_at is None:
        content.published_at = now
    content.approved_by = actor.id if actor is not None else None
    content.approved_at = now


async def _approve(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User | None,
    now: datetime,
    audit_action: str,
    trust_reason: str,
) -> ContentModel:
    from_status = content.status
    content.status = _target(content, "approve")
    _set_approval(content, actor=actor, now=now)
    await _finish(
        db, content=content, from_status=from_status, audit_action=audit_action, actor=actor
    )
    await _trust_author(db, content=content, actor=actor, reason=trust_reason, now=now)
    return content


# --- transitions ------------------------------------------------------------------------------


async def approve(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> ContentModel:
    """``pending`` → ``published`` (sets ``published_at`` if unset and the approval fields), and
    the author becomes trusted."""
    return await _approve(
        db,
        content=content,
        actor=actor,
        now=now or datetime.now(UTC),
        audit_action="moderation.approve",
        trust_reason="first_post_approved",
    )


async def reject(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User,
    reason: str | None,
    now: datetime | None = None,
) -> ContentModel:
    """``pending`` → ``hidden(rejected)``; the author stays untrusted."""
    from_status = content.status
    content.status = _target(content, "reject")
    content.hidden_reason = HiddenReason.REJECTED
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.reject",
        actor=actor,
        reason=reason,
    )


async def hide(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User,
    reason: str | None,
    now: datetime | None = None,
) -> ContentModel:
    """``published`` → ``hidden(admin)``."""
    from_status = content.status
    content.status = _target(content, "hide")
    content.hidden_reason = HiddenReason.ADMIN
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.hide",
        actor=actor,
        reason=reason,
    )


async def unhide(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> ContentModel:
    """``hidden`` → ``published``: clears ``hidden_reason``, keeps ``published_at``, resets
    ``report_count`` and dismisses the open reports.

    Unhiding a rejected post/thread is an approval: it also sets the approval fields (and
    ``published_at`` if it was never published) and trusts the author; the audit row carries
    ``"approved": true``.
    """
    now = now or datetime.now(UTC)
    from_status = content.status
    content.status = _target(content, "unhide")
    approving = (
        content_type_of(content) in REVIEWED_TYPES
        and content.hidden_reason == HiddenReason.REJECTED
    )
    content.hidden_reason = None
    if approving:
        _set_approval(content, actor=actor, now=now)
    await _dismiss_open_reports(db, content=content, actor=actor, now=now)
    await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.unhide",
        actor=actor,
        extra={"approved": True} if approving else None,
    )
    if approving:
        await _trust_author(db, content=content, actor=actor, reason="first_post_approved", now=now)
    return content


async def delete(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> ContentModel:
    """Any non-deleted status → ``deleted`` (soft: sets ``deleted_at``)."""
    from_status = content.status
    content.status = _target(content, "delete")
    content.deleted_at = now or datetime.now(UTC)
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.delete",
        actor=actor,
    )


async def restore(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> ContentModel:
    """``deleted`` → ``published`` (or ``pending`` if never approved); clears ``deleted_at`` and
    ``hidden_reason``. Back in public, it starts clean like an unhide: open reports dismissed,
    ``report_count`` reset (otherwise the next report would hide it again)."""
    now = now or datetime.now(UTC)
    from_status = content.status
    content.status = _target(content, "restore")
    content.deleted_at = None
    content.hidden_reason = None
    if content.status == _PUB:
        await _dismiss_open_reports(db, content=content, actor=actor, now=now)
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.restore",
        actor=actor,
    )


# --- automatic moderation ---------------------------------------------------------------------


async def auto_hide_if_reported(
    db: AsyncSession, *, content: ContentModel, now: datetime | None = None
) -> bool:
    """Hide published ``content`` (``hidden(auto_reports)``) once it has open reports from
    ``REPORT_AUTO_HIDE_THRESHOLD`` distinct reporters (0 turns auto-hide off). Returns True when it
    was hidden."""
    threshold = settings.REPORT_AUTO_HIDE_THRESHOLD
    if threshold <= 0 or content.status != _PUB:
        return False
    reporters = await _open_reporter_count(
        db, content_type=content_type_of(content), content_id=content.id
    )
    if reporters < threshold:
        return False
    content.status = _target(content, "hide")
    content.hidden_reason = HiddenReason.AUTO_REPORTS
    await _finish(
        db,
        content=content,
        from_status=_PUB,
        audit_action="moderation.auto_hidden",
        actor=None,
    )
    return True


async def auto_approve_stale(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Approve (no actor) every post and thread pending for more than ``AUTO_APPROVE_AFTER_DAYS``
    days, trusting their authors. Returns how many were approved; 0 when the setting is 0."""
    days = settings.AUTO_APPROVE_AFTER_DAYS
    if days <= 0:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    approved = 0
    for content_type in (ContentType.POST, ContentType.THREAD):
        model = MODELS[content_type]
        stale = await db.scalars(
            select(model)
            .where(model.status == _P, model.created_at < cutoff)
            .order_by(model.created_at, model.id)
        )
        for content in stale.all():
            await _approve(
                db,
                content=content,
                actor=None,
                now=now,
                audit_action="moderation.auto_approved",
                trust_reason="auto_approve",
            )
            approved += 1
    return approved
