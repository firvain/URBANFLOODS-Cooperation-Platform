"""Content moderation: the single place where a post, thread, reply or comment changes status
(besides the author's own soft delete in the content modules). Never commits; the caller does.

State machine (docs/PLAN.md, "State machines"), enforced by :data:`TRANSITIONS`:

- ``pending`` → approve → ``published``; ``pending`` → reject → ``hidden(rejected)``
- ``published`` → hide → ``hidden(admin)`` (or ``hidden(auto_reports)`` via
  :func:`auto_hide_if_reported`)
- ``hidden`` → unhide → ``published`` (an approval when it was ``hidden(rejected)``)
- any non-deleted → delete → ``deleted`` (``hidden_reason`` is kept)
- ``deleted`` → restore → ``hidden`` with the same ``hidden_reason`` if it was hidden when deleted
  (by an admin, auto-hidden or rejected); otherwise ``published``, or ``pending`` if it was never
  approved
- ``hidden(rejected)`` → resubmit (by the author, after editing) → ``pending``

Deleting never changes ``hidden_reason`` (neither here nor in the authors' own soft delete), so a
restore cannot republish content that was taken down: an author deleting their own hidden post
and an admin restoring it later gets it back hidden, its open reports still open.

A rejection's reason is stored on the post/thread as ``moderation_note`` (plain text, shown to the
author); every approval clears it, a resubmission keeps it until the next decision. A ``hide``
reason stays in the audit row only. A rejection also stamps ``rejected_at`` (with or without a
reason); every approval clears it, and resubmit, delete and restore keep it. It marks the item as
rejected-and-resubmitted in the admin queue and keeps it out of the auto-approve sweep.

Unhide and a restore that lands on ``published`` dismiss the item's open reports, each with its
own ``report.dismiss`` audit row (``{content_type, content_id, via}``).

Replies and comments have no ``pending`` state, so approve/reject on them is always invalid. Any
other edge raises 409 ``moderation.invalid_transition``. Every transition writes an
``moderation.<action>`` audit row with ``{"from", "to", "reason"?}``. Approving a member's
content marks them trusted (``user.trusted`` audit row). The scheduler's
:func:`auto_approve_stale` approves (no actor) stale pending posts/threads of live authors that
were never rejected, in one locking query that skips rows another transaction holds. Tag usage
counts only published posts and threads, so every post/thread transition refreshes them; the
reply/comment counters on threads and posts are kept by database triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, and_, func, literal, or_, select, union_all, update
from sqlalchemy import delete as sql_delete
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, contains_eager, joinedload

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import attachment as crud_attachment
from app.crud import user as crud_user
from app.crud.audit import log_action
from app.crud.tag import recount_tag_usage
from app.db.enums import ContentStatus, ContentType, HiddenReason, ReportStatus
from app.db.models import (
    AuditLog,
    Comment,
    KnowbaseLink,
    Post,
    Reply,
    Report,
    Thread,
    User,
    post_tags,
    thread_tags,
)
from app.services.sanitize import plain_text

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
# Posts and threads have INTEGER ids (replies and comments BIGINT): a larger id cannot exist, and
# Postgres would reject it as "integer out of range" rather than find nothing.
MAX_INT_ID = 2**31 - 1
# The longest ``moderation_note`` stored (the same limit as the reason in the request body).
NOTE_MAX_LENGTH = 500

_P = ContentStatus.PENDING
_PUB = ContentStatus.PUBLISHED
_H = ContentStatus.HIDDEN
_D = ContentStatus.DELETED

# action -> {from status: to status}. ``restore`` goes back to ``hidden`` instead when the content
# still has a ``hidden_reason`` (it was hidden when deleted), else to ``pending`` when it was never
# approved (no ``published_at``); see :func:`_target`.
TRANSITIONS: dict[str, dict[ContentStatus, ContentStatus]] = {
    "approve": {_P: _PUB},
    "reject": {_P: _H},
    "hide": {_PUB: _H},
    "unhide": {_H: _PUB},
    "delete": {_P: _D, _PUB: _D, _H: _D},
    "restore": {_D: _PUB},  # or _H (was hidden), or _P (never approved)
    "resubmit": {_H: _P},
}
_REVIEW_ACTIONS = frozenset({"approve", "reject", "resubmit"})


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
    nullable side of the author outer join, hence ``of=``) until the transaction ends. An id
    beyond the column's range is None without a query.
    """
    model = MODELS[content_type]
    if content_type in REVIEWED_TYPES and content_id > MAX_INT_ID:
        return None
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
    with its author and category loaded. An item that vanished (purged) between the page read
    and the row load is left out of ``items``."""
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
            select(model)
            .where(model.id.in_(ids))
            .options(joinedload(model.author), joinedload(model.category))
        )
        for obj in rows.unique():
            loaded[(content_type, obj.id)] = obj
    # A row purged between the page read and this load is skipped (``total`` still counts it).
    keys = [(ContentType(row.content_type), row.id) for row in page]
    items = [(key[0], loaded[key]) for key in keys if key in loaded]
    return total, items


async def open_reporter_count(
    db: AsyncSession, *, content_type: ContentType, content_id: int
) -> int:
    """Distinct reporters with an open report on the item (anonymised ones, NULL, not counted):
    the content's ``report_count`` and what the auto-hide threshold is compared with."""
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
    if action == "resubmit" and content.hidden_reason != HiddenReason.REJECTED:
        raise invalid_transition(action, status)
    if action == "restore":
        if content.hidden_reason is not None:
            return _H
        if content_type in REVIEWED_TYPES and content.published_at is None:
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
    db: AsyncSession, *, content: ContentModel, actor: User | None, now: datetime, via: str
) -> None:
    """Dismiss every open report on ``content`` and reset its ``report_count``. Each report gets
    its ``report.dismiss`` audit row (``{content_type, content_id, via}``, ``via`` naming the
    action that closed it), as closing it from the reports page does."""
    content_type = content_type_of(content)
    actor_id = actor.id if actor is not None else None
    rows = await db.execute(
        update(Report)
        .where(
            Report.content_type == content_type,
            Report.content_id == content.id,
            Report.status == ReportStatus.OPEN,
        )
        .values(status=ReportStatus.DISMISSED, resolved_by=actor_id, resolved_at=now)
        .returning(Report.id)
        .execution_options(synchronize_session="fetch")
    )
    content.report_count = 0
    for report_id in sorted(rows.scalars().all()):
        await log_action(
            db,
            actor_id=actor_id,
            action="report.dismiss",
            target_type="report",
            target_id=report_id,
            metadata={"content_type": content_type.value, "content_id": content.id, "via": via},
        )


async def _trust_author(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User | None,
    reason: str,
    now: datetime,
) -> bool:
    """Mark the author trusted and audit it, unless they already are trusted or the account is
    gone (no author, anonymised or banned: trusting it would undo ``anonymise_user``). Returns
    True when this call made them trusted."""
    if content.author_id is None:
        return False
    author = await db.get(User, content.author_id)
    if author is None or author.deleted_at is not None or not author.is_active:
        return False
    if not await crud_user.set_trusted(db, user=author, trusted=True, now=now):
        return False
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
    return True


def _set_approval(content: ContentModel, *, actor: User | None, now: datetime) -> None:
    """The approval fields of a post/thread; ``published_at`` only if it was never set. Clears
    the last rejection (``moderation_note`` and ``rejected_at``): used by approve, the unhide of a
    rejected item and the auto-approve sweep."""
    if content.published_at is None:
        content.published_at = now
    content.approved_by = actor.id if actor is not None else None
    content.approved_at = now
    content.moderation_note = None
    content.rejected_at = None


async def _approve(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User | None,
    now: datetime,
    audit_action: str,
    trust_reason: str,
) -> bool:
    """Approve ``content``; True when its author became trusted by it."""
    from_status = content.status
    content.status = _target(content, "approve")
    _set_approval(content, actor=actor, now=now)
    await _finish(
        db, content=content, from_status=from_status, audit_action=audit_action, actor=actor
    )
    return await _trust_author(db, content=content, actor=actor, reason=trust_reason, now=now)


# --- transitions ------------------------------------------------------------------------------


class Approval(NamedTuple):
    """What :func:`approve` and :func:`unhide` did: the content, whether it was an approval
    (always for ``approve``; for ``unhide`` only of a rejected post/thread) and whether its author
    became trusted by this very call (the approval email says so)."""

    content: ContentModel
    approved: bool
    newly_trusted: bool


async def approve(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> Approval:
    """``pending`` → ``published`` (sets ``published_at`` if unset and the approval fields), and
    the author becomes trusted."""
    newly_trusted = await _approve(
        db,
        content=content,
        actor=actor,
        now=now or datetime.now(UTC),
        audit_action="moderation.approve",
        trust_reason="first_post_approved",
    )
    return Approval(content, True, newly_trusted)


async def reject(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User,
    reason: str | None,
    now: datetime | None = None,
) -> ContentModel:
    """``pending`` → ``hidden(rejected)``; the author stays untrusted. ``reason`` (as plain
    text) becomes the item's ``moderation_note``, which the author sees; none clears it.
    ``rejected_at`` is set to ``now`` either way: from then on the item is never auto-approved
    (until an admin approves it) and shows as resubmitted in the queue."""
    from_status = content.status
    content.status = _target(content, "reject")
    content.hidden_reason = HiddenReason.REJECTED
    content.rejected_at = now or datetime.now(UTC)
    content.moderation_note = note = plain_text(reason, NOTE_MAX_LENGTH)
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.reject",
        actor=actor,
        reason=note,
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


def _unhide_approves(content: ContentModel) -> bool:
    """Whether unhiding ``content`` is an approval: a post or thread hidden as rejected."""
    return (
        content_type_of(content) in REVIEWED_TYPES
        and content.hidden_reason == HiddenReason.REJECTED
    )


async def unhide(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> Approval:
    """``hidden`` → ``published``: clears ``hidden_reason``, keeps ``published_at``, resets
    ``report_count`` and dismisses the open reports.

    Unhiding a rejected post/thread is an approval: it also sets the approval fields (and
    ``published_at`` if it was never published) and trusts the author; the audit row carries
    ``"approved": true``. ``newly_trusted`` is always False for a plain unhide.
    """
    now = now or datetime.now(UTC)
    from_status = content.status
    content.status = _target(content, "unhide")
    approving = _unhide_approves(content)
    content.hidden_reason = None
    if approving:
        _set_approval(content, actor=actor, now=now)
    await _dismiss_open_reports(db, content=content, actor=actor, now=now, via="unhide")
    await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.unhide",
        actor=actor,
        extra={"approved": True} if approving else None,
    )
    newly_trusted = approving and await _trust_author(
        db, content=content, actor=actor, reason="first_post_approved", now=now
    )
    return Approval(content, approving, newly_trusted)


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
    """``deleted`` → back where it was; clears ``deleted_at``.

    - Hidden when deleted (``hidden_reason`` set: ``admin``, ``auto_reports`` or ``rejected``):
      ``hidden`` with the same reason. Open reports stay open and ``report_count`` stays;
      ``rejected_at`` and ``moderation_note`` stay too, so a rejected item can be resubmitted by
      its author as before. The audit row carries ``hidden_reason``.
    - Otherwise ``published``, or ``pending`` if never approved. Back in public, it starts clean
      like an unhide: open reports dismissed (each audited), ``report_count`` reset (otherwise
      the next report would hide it again).
    """
    now = now or datetime.now(UTC)
    from_status = content.status
    content.status = _target(content, "restore")
    content.deleted_at = None
    extra: dict[str, Any] | None = None
    if content.status == _H:
        extra = {"hidden_reason": HiddenReason(content.hidden_reason).value}
    if content.status == _PUB:
        await _dismiss_open_reports(db, content=content, actor=actor, now=now, via="restore")
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.restore",
        actor=actor,
        extra=extra,
    )


async def resubmit(
    db: AsyncSession, *, content: ContentModel, actor: User, now: datetime | None = None
) -> ContentModel:
    """``hidden(rejected)`` → ``pending``: the author (``actor``; the caller checks it) sends
    their edited post/thread for approval again. Clears ``hidden_reason`` and keeps
    ``moderation_note``, so the author still sees why it was rejected until the next decision.
    Keeps ``rejected_at`` too, so an admin must review the edit (the auto-approve sweep skips
    it). Trusts nobody."""
    from_status = content.status
    content.status = _target(content, "resubmit")
    content.hidden_reason = None
    return await _finish(
        db,
        content=content,
        from_status=from_status,
        audit_action="moderation.resubmit",
        actor=actor,
    )


# --- permanent deletion -----------------------------------------------------------------------

# The audit row keeps at most this much of a purged post's/thread's title (never the body).
PURGE_TITLE_MAX = 200


@dataclass(frozen=True)
class PurgeResult:
    content_type: ContentType
    id: int
    children_deleted: int
    attachments_deleted: int
    reports_resolved: int
    # ``(storage_path, thumb_path)`` of the deleted attachments: the caller removes the files
    # once the transaction has committed.
    files: list[tuple[str, str | None]]


def _children(content: ContentModel) -> tuple[type[Any], ColumnElement[bool]] | None:
    """The model and parent condition of the rows that go with ``content``: a post's comments, a
    thread's replies (all levels), a reply's own children; a comment has none."""
    if isinstance(content, Post):
        return Comment, Comment.post_id == content.id
    if isinstance(content, Thread):
        return Reply, Reply.thread_id == content.id
    if isinstance(content, Reply):
        return Reply, Reply.parent_reply_id == content.id
    return None


async def _delete_children(
    db: AsyncSession, *, model: type[Any], parent: ColumnElement[bool]
) -> list[int]:
    """``DELETE ... WHERE <parent> RETURNING id``: every child at the moment of the delete, also
    one added after an earlier read. Second-level replies go first, so their parent's
    ``ON DELETE SET NULL`` has nothing left to touch."""
    deleted: list[int] = []
    steps = [parent]
    if model is Reply:
        steps = [parent & Reply.parent_reply_id.is_not(None), parent]
    for where in steps:
        stmt = (
            sql_delete(model)
            .where(where)
            .returning(model.id)
            .execution_options(synchronize_session=False)
        )
        deleted.extend((await db.scalars(stmt)).all())
    return deleted


async def _tag_ids(db: AsyncSession, content: ContentModel) -> list[int]:
    if isinstance(content, Post):
        stmt = select(post_tags.c.tag_id).where(post_tags.c.post_id == content.id)
    elif isinstance(content, Thread):
        stmt = select(thread_tags.c.tag_id).where(thread_tags.c.thread_id == content.id)
    else:
        return []
    return list((await db.scalars(stmt)).all())


async def _resolve_open_reports(
    db: AsyncSession,
    *,
    targets: list[tuple[ContentType, list[int]]],
    actor: User | None,
    now: datetime,
) -> int:
    """Resolve (by ``actor``; by nobody for the retention sweep) every open report on the given
    items, each with its ``report.resolve`` audit row (``purge: true`` in the metadata), as
    closing a report from the reports page does; closed ones stay as they are. The rows are
    kept: they are part of the moderation trail. Returns how many."""
    conditions = [
        (Report.content_type == content_type) & Report.content_id.in_(ids)
        for content_type, ids in targets
        if ids
    ]
    if not conditions:
        return 0
    actor_id = actor.id if actor is not None else None
    stmt = (
        update(Report)
        .where(or_(*conditions), Report.status == ReportStatus.OPEN)
        .values(status=ReportStatus.RESOLVED, resolved_by=actor_id, resolved_at=now)
        .returning(Report.id, Report.content_type, Report.content_id)
        .execution_options(synchronize_session=False)
    )
    rows = sorted((await db.execute(stmt)).all(), key=lambda row: row.id)
    for row in rows:
        await log_action(
            db,
            actor_id=actor_id,
            action="report.resolve",
            target_type="report",
            target_id=row.id,
            metadata={
                "content_type": ContentType(row.content_type).value,
                "content_id": row.content_id,
                "purge": True,
            },
        )
    return len(rows)


async def purge(
    db: AsyncSession,
    *,
    content: ContentModel,
    actor: User | None,
    now: datetime | None = None,
    reason: str | None = None,
) -> PurgeResult:
    """Hard-delete ``content`` (any status; the caller has loaded it ``FOR UPDATE``) with what
    belongs to it:

    - a post's comments, tag rows and KNOWBASE links; a thread's replies (all levels), tag rows
      and links; a top-level reply's child replies; a comment alone. Children are deleted by
      their parent's id with ``RETURNING`` (the locked parent row also makes a concurrent insert
      wait: its foreign-key check needs a key-share lock on it);
    - open reports on all of them are resolved by ``actor``, each with its ``report.resolve``
      audit row (the reports stay);
    - attachments the deleted rows used (a post's cover, paths in any deleted body) are
      hard-deleted when nothing else uses them any more (any uploader); their files are the
      caller's to remove after commit (:attr:`PurgeResult.files`);
    - tag usage is recounted; the reply/comment counters follow by trigger;
    - audit ``moderation.purge`` with counts, the deleted attachments' ids and uploaders, a
      post's/thread's title and ``reason`` when given; never a body, a path or a file name.

    ``actor`` is None for the retention sweep (:func:`purge_expired_deleted`): the reports are
    then resolved by nobody and the audit rows have no actor.
    """
    now = now or datetime.now(UTC)
    content_type = content_type_of(content)
    model = MODELS[content_type]
    content_id = content.id
    from_status = content.status
    title = getattr(content, "title", None)
    children = _children(content)

    bodies: list[tuple[type[Any], ColumnElement[bool]]] = [(model, model.id == content_id)]
    if children is not None:
        bodies.append(children)
    attachment_ids = await crud_attachment.referenced_attachment_ids(
        db,
        bodies=bodies,
        cover_of=Post.id == content_id if content_type == ContentType.POST else None,
    )
    tag_ids = await _tag_ids(db, content)

    if content_type in REVIEWED_TYPES:
        await db.execute(
            sql_delete(KnowbaseLink)
            .where(KnowbaseLink.content_type == content_type, KnowbaseLink.content_id == content_id)
            .execution_options(synchronize_session=False)
        )
    child_ids: list[int] = []
    targets = [(content_type, [content_id])]
    if children is not None:
        child_model, parent = children
        child_ids = await _delete_children(db, model=child_model, parent=parent)
        targets.append((_TYPES[child_model], child_ids))
    await db.delete(content)
    await db.flush()

    reports_resolved = await _resolve_open_reports(db, targets=targets, actor=actor, now=now)
    await recount_tag_usage(db, tag_ids=tag_ids)
    deleted = await crud_attachment.delete_unused_attachments(db, attachment_ids=attachment_ids)

    metadata: dict[str, Any] = {
        "from": from_status.value,
        "content_type": content_type.value,
        "content_id": content_id,
    }
    if title is not None:
        metadata["title"] = title[:PURGE_TITLE_MAX]
    metadata.update(
        children_deleted=len(child_ids),
        attachments_deleted=len(deleted),
        reports_resolved=reports_resolved,
        attachments=[{"id": a.id, "uploader_id": a.uploader_id} for a in deleted],
    )
    if reason is not None:
        metadata["reason"] = reason
    await log_action(
        db,
        actor_id=actor.id if actor is not None else None,
        action="moderation.purge",
        target_type=content_type.value,
        target_id=content_id,
        metadata=metadata,
    )
    return PurgeResult(
        content_type=content_type,
        id=content_id,
        children_deleted=len(child_ids),
        attachments_deleted=len(deleted),
        reports_resolved=reports_resolved,
        files=[(a.storage_path, a.thumb_path) for a in deleted],
    )


# --- retention of deleted content -------------------------------------------------------------

# The audit reason of a purge by the retention sweep.
RETENTION_REASON = "retention"


def _due(model: type[Any], cutoff: datetime) -> ColumnElement[bool]:
    return (model.status == _D) & (model.deleted_at < cutoff)


def _reply_holds_others(cutoff: datetime) -> ColumnElement[bool]:
    """A reply has a child that is not deleted (or deleted after ``cutoff``): it is shown as a
    placeholder holding those replies, and purging it would delete them with it."""
    child = aliased(Reply)
    return (
        select(child.id)
        .where(
            child.parent_reply_id == Reply.id,
            or_(child.status != _D, child.deleted_at.is_(None), child.deleted_at >= cutoff),
        )
        .exists()
    )


def _still_due(content: ContentModel | None, cutoff: datetime) -> bool:
    return (
        content is not None
        and content.status == _D
        and content.deleted_at is not None
        and content.deleted_at < cutoff
    )


async def _due_rows(
    db: AsyncSession, *, types: tuple[ContentType, ContentType], cutoff: datetime, limit: int
) -> list[tuple[ContentType, int]]:
    """``(type, id)`` of up to ``limit`` items of ``types`` deleted before ``cutoff``, oldest
    deletion first."""
    selects = []
    for content_type in types:
        model = MODELS[content_type]
        conditions = [_due(model, cutoff)]
        if model is Reply:
            conditions.append(~_reply_holds_others(cutoff))
        selects.append(
            select(
                literal(content_type.value).label("content_type"),
                model.id.label("id"),
                model.deleted_at.label("deleted_at"),
            ).where(*conditions)
        )
    due = union_all(*selects).subquery()
    rows = await db.execute(
        select(due.c.content_type, due.c.id)
        .order_by(due.c.deleted_at.asc(), due.c.content_type, due.c.id)
        .limit(limit)
    )
    return [(ContentType(row.content_type), row.id) for row in rows]


async def purge_expired_deleted(
    db: AsyncSession, *, cutoff: datetime, limit: int, now: datetime | None = None
) -> list[PurgeResult]:
    """Purge (no actor, reason ``retention``) up to ``limit`` items soft-deleted before
    ``cutoff``, oldest deletion first: posts and threads (with everything :func:`purge` takes
    with them), then comments and replies.

    A deleted reply is skipped while it still has a child that is not deleted, or deleted after
    ``cutoff``: it is shown as a placeholder holding other members' replies, which its purge
    would delete. It goes in a later run once all its children are due too.

    Each item is loaded ``FOR UPDATE`` and checked again (it may have been restored or purged
    meanwhile, also by this very run as a child of an earlier item); those are skipped.
    """
    now = now or datetime.now(UTC)
    results: list[PurgeResult] = []
    for types in (
        (ContentType.POST, ContentType.THREAD),
        (ContentType.COMMENT, ContentType.REPLY),
    ):
        remaining = limit - len(results)
        if remaining <= 0:
            break
        for content_type, content_id in await _due_rows(
            db, types=types, cutoff=cutoff, limit=remaining
        ):
            content = await get_content(
                db, content_type=content_type, content_id=content_id, for_update=True
            )
            if not _still_due(content, cutoff):
                continue
            if isinstance(content, Reply):
                holds_others = select(_reply_holds_others(cutoff)).where(Reply.id == content.id)
                if await db.scalar(holds_others):
                    continue
            results.append(
                await purge(db, content=content, actor=None, now=now, reason=RETENTION_REASON)
            )
    return results


# --- the deleted items list (admins) ----------------------------------------------------------

# The audit actions that soft-delete a post or thread: an admin's moderation action, or the
# delete endpoint (its author, or an admin).
DELETE_ACTIONS = ("moderation.delete", "post.deleted", "thread.deleted")


@dataclass(frozen=True)
class DeletedItem:
    content_type: ContentType
    content: Post | Thread
    # Who deleted it (the latest deletion's audit row); None when unknown or the row has no actor.
    deleted_by: User | None


async def _deleters(
    db: AsyncSession, *, targets: list[tuple[ContentType, int]]
) -> dict[tuple[ContentType, int], User | None]:
    """The actor of the latest delete audit row of each target, in one query."""
    if not targets:
        return {}
    conditions = []
    for content_type in REVIEWED_TYPES:
        ids = [content_id for ct, content_id in targets if ct == content_type]
        if ids:
            conditions.append(
                (AuditLog.target_type == content_type.value) & AuditLog.target_id.in_(ids)
            )
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(DELETE_ACTIONS), or_(*conditions))
        .ext(distinct_on(AuditLog.target_type, AuditLog.target_id))
        .order_by(
            AuditLog.target_type,
            AuditLog.target_id,
            AuditLog.created_at.desc(),
            AuditLog.id.desc(),
        )
        .options(joinedload(AuditLog.actor))
    )
    return {(ContentType(row.target_type), row.target_id): row.actor for row in rows.unique().all()}


async def list_deleted(
    db: AsyncSession,
    *,
    content_type: ContentType | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[DeletedItem]]:
    """``(total, items)`` of deleted posts and threads (or only ``content_type``), newest
    deletion first, each with its author and category loaded and who deleted it."""
    types = [content_type] if content_type is not None else [ContentType.POST, ContentType.THREAD]
    selects = [
        select(
            literal(ct.value).label("content_type"),
            MODELS[ct].id.label("id"),
            MODELS[ct].deleted_at.label("deleted_at"),
        ).where(MODELS[ct].status == _D)
        for ct in types
    ]
    deleted = (union_all(*selects) if len(selects) > 1 else selects[0]).subquery()
    total = (await db.execute(select(func.count()).select_from(deleted))).scalar_one()
    page = [
        (ContentType(row.content_type), row.id)
        for row in await db.execute(
            select(deleted.c.content_type, deleted.c.id)
            .order_by(
                deleted.c.deleted_at.desc().nulls_last(),
                deleted.c.content_type,
                deleted.c.id.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
    ]

    loaded: dict[tuple[ContentType, int], Post | Thread] = {}
    for ct in REVIEWED_TYPES:
        ids = [content_id for page_type, content_id in page if page_type == ct]
        if not ids:
            continue
        model = MODELS[ct]
        rows = await db.scalars(
            select(model)
            .where(model.id.in_(ids))
            .options(joinedload(model.author), joinedload(model.category))
        )
        for obj in rows.unique():
            loaded[(ct, obj.id)] = obj
    deleters = await _deleters(db, targets=page)
    items = [
        DeletedItem(ct, loaded[(ct, content_id)], deleters.get((ct, content_id)))
        for ct, content_id in page
        if (ct, content_id) in loaded
    ]
    return total, items


async def content_slugs(
    db: AsyncSession, *, post_ids: set[int], thread_ids: set[int]
) -> dict[tuple[ContentType, int], str]:
    """``{(type, id): slug}`` of the posts and threads among the ids that still exist (any
    status): one query per type. Ids beyond the INTEGER range cannot exist and are ignored."""
    slugs: dict[tuple[ContentType, int], str] = {}
    for content_type, ids in ((ContentType.POST, post_ids), (ContentType.THREAD, thread_ids)):
        ids = {i for i in ids if 0 < i <= MAX_INT_ID}
        if not ids:
            continue
        model = MODELS[content_type]
        rows = await db.execute(select(model.id, model.slug).where(model.id.in_(ids)))
        slugs.update({(content_type, row.id): row.slug for row in rows})
    return slugs


# --- automatic moderation ---------------------------------------------------------------------


async def auto_hide_if_reported(
    db: AsyncSession,
    *,
    content: ContentModel,
    now: datetime | None = None,
    reporters: int | None = None,
) -> bool:
    """Hide published ``content`` (``hidden(auto_reports)``) once it has open reports from
    ``REPORT_AUTO_HIDE_THRESHOLD`` distinct reporters (0 turns auto-hide off). Returns True when it
    was hidden. ``reporters`` is the caller's fresh :func:`open_reporter_count`, if it has one."""
    threshold = settings.REPORT_AUTO_HIDE_THRESHOLD
    if threshold <= 0 or content.status != _PUB:
        return False
    if reporters is None:
        reporters = await open_reporter_count(
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


@dataclass(frozen=True)
class ApprovedItem:
    """One post or thread the auto-approve sweep approved (for the author emails it sends once
    the sweep has committed)."""

    content_type: ContentType
    content_id: int
    newly_trusted: bool


def _auto_approvable(model: type[Any], cutoff: datetime) -> ColumnElement[bool]:
    """The rows :func:`auto_approve_stale` may approve (with ``User`` joined on the author):
    pending since before ``cutoff``, never rejected (or approved since), by an author who is
    active and not erased."""
    return and_(
        model.status == _P,
        model.created_at < cutoff,
        model.rejected_at.is_(None),
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    )


async def auto_approve_stale(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    approved: list[ApprovedItem] | None = None,
) -> int:
    """Approve (no actor) every post and thread pending for more than ``AUTO_APPROVE_AFTER_DAYS``
    days, trusting their authors. Returns how many were approved; 0 when the setting is 0. Each
    approval is appended to ``approved`` when it is given.

    Skipped, so they wait for an admin: items without an author or whose author is banned or
    erased, and items with a ``rejected_at`` (rejected, then resubmitted or restored: the edit
    needs an admin's eyes).

    One query per content type selects the items and their authors and locks both rows
    (``FOR UPDATE OF <content>, users SKIP LOCKED``), refreshing the session's copies. Postgres
    checks the conditions on the latest committed rows once it holds the locks, so a decision or
    ban committed before that wins; an item whose content or author row another transaction
    holds (an admin deciding, a ban, an erasure in flight) is skipped, never waited for, and
    waits for the next run. Never waiting for those rows also keeps the sweep from deadlocking
    against them or blocking an admin.
    """
    days = settings.AUTO_APPROVE_AFTER_DAYS
    if days <= 0:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    count = 0
    for content_type in (ContentType.POST, ContentType.THREAD):
        model = MODELS[content_type]
        stale = await db.scalars(
            select(model)
            .join(User, User.id == model.author_id)
            .where(_auto_approvable(model, cutoff))
            .options(contains_eager(model.author))
            .order_by(model.created_at, model.id)
            .with_for_update(of=(model, User), skip_locked=True)
            .execution_options(populate_existing=True)
        )
        for content in stale.all():
            newly_trusted = await _approve(
                db,
                content=content,
                actor=None,
                now=now,
                audit_action="moderation.auto_approved",
                trust_reason="auto_approve",
            )
            count += 1
            if approved is not None:
                approved.append(ApprovedItem(content_type, content.id, newly_trusted))
    return count
