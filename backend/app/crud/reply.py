"""Forum reply data access: list (top-level replies with one level of children), get, create,
update (author within 24 h, or an admin) and soft delete. Never commits; the caller
(``get_db_tx``) does.

Replies are ``published`` on creation (no trust gate). Nesting is one level deep: a reply's
parent must be a top-level reply of the same thread. This module checks that first; the
``replies_one_level`` trigger (migration 0005) is the last line and its ``replies.nesting``
error is mapped to the same 422. ``threads.reply_count`` and ``threads.last_activity_at`` are
kept by the ``replies_reply_count`` trigger, so nothing here touches them.

A locked thread takes no new replies from anyone (admins unlock first) and blocks edits by
authors; admins may still edit, and deleting is always allowed.

Bodies use the comment allow-list (:func:`app.crud.comment.sanitize_comment_html`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from app.core.exceptions import AppError, validation_error
from app.crud.comment import sanitize_comment_html
from app.crud.thread import not_found as thread_not_found
from app.crud.thread import thread_locked
from app.crud.visibility import is_admin, is_visible, visible_filter
from app.db.enums import ContentStatus
from app.db.models import Reply, Thread, User
from app.services.sanitize import html_to_text

BODY_TEXT_MAX_LENGTH = 10_000
EDIT_WINDOW = timedelta(hours=24)
NESTING_ERROR = "replies.nesting"


# --- errors -----------------------------------------------------------------------------------


def not_found() -> AppError:
    return AppError(404, "replies.not_found", "Reply not found.")


def forbidden() -> AppError:
    return AppError(403, "replies.forbidden", "You cannot change this reply.")


def thread_not_published() -> AppError:
    return AppError(422, "threads.not_published", "Replies are open on published threads only.")


def invalid_parent() -> AppError:
    return validation_error({"parent_reply_id": "invalid"})


def _clean_body(body_html: str) -> tuple[str, str]:
    """``(sanitised html, plain text)``; 422 ``body_html`` = ``empty`` / ``too_long``."""
    html = sanitize_comment_html(body_html)
    if not html:
        raise validation_error({"body_html": "empty"})
    text = html_to_text(html)
    if len(text) > BODY_TEXT_MAX_LENGTH:
        raise validation_error({"body_html": "too_long"})
    return html, text


# --- reads ------------------------------------------------------------------------------------


def _with_author(stmt: Any) -> Any:
    return stmt.options(
        joinedload(Reply.author).joinedload(User.organisation),
        joinedload(Reply.author).joinedload(User.avatar),
    )


def _top_level_condition(thread: Thread, user: User | None) -> Any:
    """Top-level replies of ``thread`` that ``user`` sees, plus those it does not see (deleted,
    or hidden from it) that still have a child it sees: those are shown as placeholders."""
    child = aliased(Reply)
    has_visible_child = exists().where(
        child.parent_reply_id == Reply.id, visible_filter(child, user)
    )
    return and_(
        Reply.thread_id == thread.id,
        Reply.parent_reply_id.is_(None),
        or_(visible_filter(Reply, user), has_visible_child),
    )


async def list_replies(
    db: AsyncSession, *, thread: Thread, user: User | None, skip: int = 0, limit: int = 20
) -> tuple[int, list[Reply]]:
    """``(total, top-level replies)`` on ``thread``, oldest first; ``total`` counts top-level
    replies only. The caller checks that ``user`` may see the thread.

    Each returned reply carries two plain (unmapped) attributes for the schema:
    ``visible_children`` (its children ``user`` sees, oldest first) and ``is_placeholder``
    (``user`` may not see the reply itself; only its place in the thread is kept).
    """
    condition = _top_level_condition(thread, user)
    total_stmt = select(func.count()).select_from(select(Reply.id).where(condition).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = _with_author(
        select(Reply).where(condition).order_by(Reply.created_at.asc(), Reply.id.asc())
    )
    parents = list((await db.scalars(stmt.offset(skip).limit(limit))).unique().all())
    if not parents:
        return total, []

    children_stmt = _with_author(
        select(Reply)
        .where(
            Reply.parent_reply_id.in_([parent.id for parent in parents]),
            visible_filter(Reply, user),
        )
        .order_by(Reply.created_at.asc(), Reply.id.asc())
    )
    children = (await db.scalars(children_stmt)).unique().all()
    by_parent: dict[int, list[Reply]] = {parent.id: [] for parent in parents}
    for child in children:
        assert child.parent_reply_id is not None
        by_parent[child.parent_reply_id].append(child)
    # Plain attributes, not the ``children`` relationship: assigning a filtered list to the
    # relationship would detach the hidden children on the next flush.
    for parent in parents:
        parent.visible_children = by_parent[parent.id]  # type: ignore[attr-defined]
        parent.is_placeholder = not is_visible(parent, user)  # type: ignore[attr-defined]
    return total, parents


async def get_reply(db: AsyncSession, *, reply_id: int) -> Reply | None:
    """The reply (any status), author loaded and refreshed from the database."""
    stmt = _with_author(select(Reply).where(Reply.id == reply_id)).execution_options(
        populate_existing=True
    )
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_visible_thread(db: AsyncSession, *, thread_id: int, user: User | None) -> Thread:
    """The thread ``user`` may see (never a deleted one); 404 ``threads.not_found`` otherwise."""
    thread = await db.get(Thread, thread_id, populate_existing=True)
    if thread is None or not is_visible(thread, user):
        raise thread_not_found()
    return thread


async def get_editable_reply(db: AsyncSession, *, reply_id: int, user: User) -> Reply:
    """The reply ``user`` may change or delete: its author, or an admin.

    404 ``replies.not_found`` when it does not exist, is deleted, or ``user`` cannot see it or
    its thread; 403 ``replies.forbidden`` for anyone else. The edit window and the thread lock
    are checked by :func:`update_reply` (deleting has neither).
    """
    reply = await get_reply(db, reply_id=reply_id)
    if reply is None or reply.status == ContentStatus.DELETED or not is_visible(reply, user):
        raise not_found()
    thread = await db.get(Thread, reply.thread_id)
    if thread is None or not is_visible(thread, user):
        raise not_found()
    if reply.author_id != user.id and not is_admin(user):
        raise forbidden()
    return reply


# --- writes -----------------------------------------------------------------------------------


async def _check_parent(
    db: AsyncSession, *, thread: Thread, author: User, parent_reply_id: int
) -> None:
    """422 ``parent_reply_id`` = ``invalid`` unless the parent is a top-level reply of
    ``thread`` that ``author`` can see."""
    parent = await db.get(Reply, parent_reply_id)
    if (
        parent is None
        or parent.thread_id != thread.id
        or parent.parent_reply_id is not None
        or not is_visible(parent, author)
    ):
        raise invalid_parent()


async def create_reply(
    db: AsyncSession,
    *,
    thread: Thread,
    author: User,
    body_html: str,
    parent_reply_id: int | None = None,
    now: datetime | None = None,
) -> Reply:
    """Insert a published reply on ``thread`` and return it with its author loaded.

    404 ``threads.not_found`` when ``author`` cannot see the thread; 422
    ``threads.not_published`` when it is not published; 423 ``threads.locked`` when it is locked
    (for admins too); 422 ``parent_reply_id`` = ``invalid`` for a parent that is missing, in
    another thread, a child itself or not visible; 422 for an empty or too long body.
    """
    if not is_visible(thread, author):
        raise thread_not_found()
    if thread.status != ContentStatus.PUBLISHED:
        raise thread_not_published()
    if thread.is_locked:
        raise thread_locked()
    if parent_reply_id is not None:
        await _check_parent(db, thread=thread, author=author, parent_reply_id=parent_reply_id)
    html, text = _clean_body(body_html)
    now = now or datetime.now(UTC)
    reply = Reply(
        thread_id=thread.id,
        author_id=author.id,
        parent_reply_id=parent_reply_id,
        body_html=html,
        body_text=text,
        status=ContentStatus.PUBLISHED,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(reply)
    except IntegrityError as exc:
        # The parent became a child (or vanished) between the check and the insert.
        if NESTING_ERROR in str(exc.orig) or "fk_replies_parent_reply_id" in str(exc.orig):
            raise invalid_parent() from exc
        raise
    loaded = await get_reply(db, reply_id=reply.id)
    assert loaded is not None
    return loaded


async def update_reply(
    db: AsyncSession,
    *,
    reply: Reply,
    user: User,
    body_html: str,
    now: datetime | None = None,
) -> bool:
    """Replace the body (re-sanitised) and bump ``updated_at``. Returns whether it changed.

    Admins may edit any time, locked thread or not. The author may edit within
    :data:`EDIT_WINDOW` of creation (else 403 ``replies.forbidden``) and only while the thread
    is unlocked (else 423 ``threads.locked``); anyone else gets 403.
    """
    now = now or datetime.now(UTC)
    if not is_admin(user):
        if reply.author_id != user.id or now - reply.created_at > EDIT_WINDOW:
            raise forbidden()
        thread = await db.get(Thread, reply.thread_id)
        if thread is not None and thread.is_locked:
            raise thread_locked()
    html, text = _clean_body(body_html)
    if html == reply.body_html:
        return False
    reply.body_html, reply.body_text = html, text
    reply.updated_at = now
    await db.flush()
    return True


async def soft_delete_reply(
    db: AsyncSession, *, reply: Reply, now: datetime | None = None
) -> Reply:
    """Mark the reply deleted (``status`` + ``deleted_at``); its children stay attached (they
    are listed under a placeholder). The trigger recounts the thread."""
    reply.status = ContentStatus.DELETED
    reply.deleted_at = now or datetime.now(UTC)
    await db.flush()
    return reply
