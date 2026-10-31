"""Forum thread data access: list (visibility, pinned first, activity/newest sort, filters,
search), detail, create, update, soft delete, admin pin/lock, and KNOWBASE mentions. Never
commits; the caller (``get_db_tx``) does.

Mirrors :mod:`app.crud.post`: every read goes through :func:`app.crud.visibility.visible_filter`,
bodies are sanitised before they are stored and the status on create follows the trust model
(trusted members and admins publish immediately, everyone else's thread is ``pending``). Threads
live in ``forum`` categories only. A locked thread can still be edited by admins, not by its
author. ``reply_count`` and ``last_activity_at`` are kept up to date by the replies trigger.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, exists, func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import AppError, validation_error
from app.crud import knowbase_link as crud_links
from app.crud.post import _clean_body as clean_body
from app.crud.post import _escape_like as escape_like
from app.crud.post import _link_pairs as link_pairs
from app.crud.tag import get_or_create_tags, recount_tag_usage
from app.crud.visibility import is_admin, is_visible, visible_filter
from app.db.enums import CategoryKind, ContentStatus, ContentType, KbType
from app.db.models import Category, KnowbaseLink, Tag, Thread, User
from app.services.knowbase import KnowbaseClient
from app.services.slugs import slugify_title, unique_slug_async

ThreadSort = Literal["activity", "newest"]
SLUG_UNIQUE_CONSTRAINT = "uq_threads_slug"
SLUG_INSERT_TRIES = 3
FTS_CONFIG = literal_column("'english'::regconfig")
UPDATABLE_FIELDS = frozenset(
    {"title", "body_html", "category_id", "locale", "tags", "knowbase_links", "slug"}
)
_SIMPLE_FIELDS = ("title", "locale")


# --- errors -----------------------------------------------------------------------------------


def not_found() -> AppError:
    return AppError(404, "threads.not_found", "Thread not found.")


def forbidden() -> AppError:
    return AppError(403, "threads.forbidden", "You cannot change this thread.")


def thread_locked() -> AppError:
    return AppError(423, "threads.locked", "This thread is locked.")


def _slug_taken() -> AppError:
    return AppError(409, "threads.slug_taken", "A thread with this slug exists.")


# --- reads ------------------------------------------------------------------------------------


def _with_relations(stmt: Any) -> Any:
    """Eager loads for summaries and details: many-to-one joined, tags by selectin."""
    return stmt.options(
        joinedload(Thread.author).joinedload(User.organisation),
        joinedload(Thread.author).joinedload(User.avatar),
        joinedload(Thread.category),
        selectinload(Thread.tags),
    )


def _pinned() -> Any:
    return Thread.is_pinned.desc()


def _activity() -> tuple[Any, ...]:
    return (Thread.last_activity_at.desc(), Thread.id.desc())


def _newest() -> tuple[Any, ...]:
    return (Thread.created_at.desc(), Thread.id.desc())


async def _page(
    db: AsyncSession,
    *,
    conditions: Sequence[ColumnElement[bool]],
    order: Sequence[Any],
    skip: int,
    limit: int,
) -> tuple[int, list[Thread]]:
    total_stmt = select(func.count()).select_from(select(Thread.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = _with_relations(select(Thread).where(*conditions).order_by(*order))
    rows = await db.scalars(stmt.offset(skip).limit(limit))
    return total, list(rows.unique().all())


async def list_threads(
    db: AsyncSession,
    *,
    user: User | None,
    q: str | None = None,
    category_slug: str | None = None,
    tag_slug: str | None = None,
    author_id: int | None = None,
    locale: str | None = None,
    status: ContentStatus | None = None,
    sort: ThreadSort | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[int, list[Thread]]:
    """``(total, threads)`` visible to ``user``.

    Pinned threads come first, then the latest activity (``sort="activity"``, the default) or the
    newest thread (``sort="newest"``). ``q`` matches the full-text vector or a title substring
    and, unless a ``sort`` is asked for, orders by ``ts_rank`` then activity (no pinning: the
    best match wins). ``status`` is honoured for admins only.
    """
    conditions: list[ColumnElement[bool]] = [visible_filter(Thread, user)]
    if status is not None and is_admin(user):
        conditions.append(Thread.status == status)
    if category_slug:
        conditions.append(
            Thread.category_id.in_(
                select(Category.id).where(
                    Category.kind == CategoryKind.FORUM, Category.slug == category_slug
                )
            )
        )
    if tag_slug:
        conditions.append(Thread.tags.any(Tag.slug == tag_slug))
    if author_id is not None:
        conditions.append(Thread.author_id == author_id)
    if locale:
        conditions.append(Thread.locale == locale)

    order: tuple[Any, ...] = (_pinned(), *(_newest() if sort == "newest" else _activity()))
    query = (q or "").strip()
    if query:
        tsquery = func.plainto_tsquery(FTS_CONFIG, query)
        conditions.append(
            or_(
                Thread.fts.bool_op("@@")(tsquery),
                Thread.title.ilike(f"%{escape_like(query)}%", escape="\\"),
            )
        )
        if sort is None:
            order = (func.ts_rank(Thread.fts, tsquery).desc(), *_activity())
    return await _page(db, conditions=conditions, order=order, skip=skip, limit=limit)


async def get_thread_by_slug(db: AsyncSession, *, slug: str, user: User | None) -> Thread | None:
    """The thread with ``slug`` if ``user`` may see it."""
    stmt = _with_relations(select(Thread).where(Thread.slug == slug, visible_filter(Thread, user)))
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_thread_by_id(db: AsyncSession, *, thread_id: int) -> Thread | None:
    """The thread (any status), relations loaded and refreshed from the database."""
    stmt = _with_relations(select(Thread).where(Thread.id == thread_id)).execution_options(
        populate_existing=True
    )
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_live_thread(db: AsyncSession, *, thread_id: int, user: User) -> Thread:
    """The thread if it exists, is not deleted and ``user`` may see it; else 404."""
    thread = await get_thread_by_id(db, thread_id=thread_id)
    if thread is None or thread.status == ContentStatus.DELETED or not is_visible(thread, user):
        raise not_found()
    return thread


async def get_editable_thread(
    db: AsyncSession, *, thread_id: int, user: User, editing: bool = True
) -> Thread:
    """The thread ``user`` may edit (``editing``) or delete: its author, or an admin.

    Raises 404 ``threads.not_found`` (missing, deleted or invisible), 403 ``threads.forbidden``
    (someone else's thread) and, when ``editing``, 423 ``threads.locked`` for the author of a
    locked thread (admins may still edit it).
    """
    thread = await get_live_thread(db, thread_id=thread_id, user=user)
    admin = is_admin(user)
    if thread.author_id != user.id and not admin:
        raise forbidden()
    if editing and thread.is_locked and not admin:
        raise thread_locked()
    return thread


def _mentions_condition(kb_type: KbType, kb_id: int) -> ColumnElement[bool]:
    return exists().where(
        KnowbaseLink.content_type == ContentType.THREAD,
        KnowbaseLink.content_id == Thread.id,
        KnowbaseLink.kb_type == kb_type,
        KnowbaseLink.kb_id == kb_id,
    )


async def list_mentions(
    db: AsyncSession,
    *,
    kb_type: KbType,
    kb_id: int,
    user: User | None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[int, list[Thread]]:
    """``(total, threads)`` linking the KNOWBASE item and visible to ``user``, latest activity
    first."""
    conditions = [visible_filter(Thread, user), _mentions_condition(kb_type, kb_id)]
    return await _page(db, conditions=conditions, order=_activity(), skip=skip, limit=limit)


# --- validation helpers -----------------------------------------------------------------------


async def _checked_category(db: AsyncSession, *, category_id: int, user: User) -> Category:
    """A forum category ``user`` may open threads in. 422 ``category_id`` = ``not_found`` /
    ``invalid`` (not a forum category) / ``archived``; 403 ``threads.category_admin_only``."""
    category = await db.get(Category, category_id)
    if category is None:
        raise validation_error({"category_id": "not_found"})
    if category.kind != CategoryKind.FORUM:
        raise validation_error({"category_id": "invalid"})
    if category.is_archived:
        raise validation_error({"category_id": "archived"})
    if category.admin_only and not is_admin(user):
        raise AppError(
            403,
            "threads.category_admin_only",
            "Only administrators can open threads in this category.",
        )
    return category


async def _slug_exists(db: AsyncSession, slug: str) -> bool:
    return bool((await db.execute(select(exists().where(Thread.slug == slug)))).scalar_one())


def _is_slug_violation(exc: IntegrityError) -> bool:
    return SLUG_UNIQUE_CONSTRAINT in str(exc.orig)


# --- writes -----------------------------------------------------------------------------------


async def create_thread(
    db: AsyncSession,
    *,
    author: User,
    category_id: int,
    title: str,
    body_html: str,
    locale: str = "en",
    tag_names: Sequence[str] = (),
    knowbase_links: Sequence[Any] = (),
    knowbase: KnowbaseClient | None = None,
    now: datetime | None = None,
) -> Thread:
    """Insert a thread and return it with its relations loaded.

    Status: ``published`` (with ``published_at = now``) for trusted members and admins, else
    ``pending``; ``last_activity_at = now`` either way. Raises 422 for an empty body, a bad
    category, invalid tags or unknown KNOWBASE items; 403 ``threads.category_admin_only``; 503
    when the KNOWBASE is down.
    """
    now = now or datetime.now(UTC)
    html, text = clean_body(body_html)
    await _checked_category(db, category_id=category_id, user=author)
    links = link_pairs(knowbase_links)
    if len(links) > crud_links.MAX_LINKS:
        raise validation_error({"knowbase_links": "too_many"})
    tags = await get_or_create_tags(db, names=list(tag_names))

    publish = author.trusted_at is not None or is_admin(author)
    base = slugify_title(title)
    for attempt in range(SLUG_INSERT_TRIES):
        thread = Thread(
            author_id=author.id,
            category_id=category_id,
            title=title,
            slug=await unique_slug_async(base, lambda s: _slug_exists(db, s)),
            body_html=html,
            body_text=text,
            locale=locale,
            status=ContentStatus.PUBLISHED if publish else ContentStatus.PENDING,
            published_at=now if publish else None,
            last_activity_at=now,
        )
        try:
            # begin_nested() flushes first: attach the tags only once the thread is in the session.
            async with db.begin_nested():
                db.add(thread)
                thread.tags = list(tags)
        except IntegrityError as exc:
            # A concurrent insert took the slug between the check and the insert.
            if not _is_slug_violation(exc) or attempt == SLUG_INSERT_TRIES - 1:
                raise
            continue
        break

    if links:
        if knowbase is None:
            raise ValueError("knowbase client required to save KNOWBASE links")
        await crud_links.replace_links(
            db,
            content_type=ContentType.THREAD,
            content_id=thread.id,
            links=links,
            knowbase=knowbase,
        )
    await recount_tag_usage(db, tag_ids=[tag.id for tag in tags])
    loaded = await get_thread_by_id(db, thread_id=thread.id)
    assert loaded is not None
    return loaded


async def update_thread(
    db: AsyncSession,
    *,
    thread: Thread,
    user: User,
    data: Mapping[str, Any],
    knowbase: KnowbaseClient | None = None,
) -> list[str]:
    """Apply the fields present in ``data`` (a partial update) and return the sorted names of
    those that changed. The status, pin and lock never change here. Bodies are re-sanitised.
    Only admins may change the slug (403 ``threads.forbidden``; 409 ``threads.slug_taken``).
    The caller checks who may edit (:func:`get_editable_thread`).
    """
    unknown = set(data) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"not thread fields: {sorted(unknown)}")
    changed: set[str] = set()

    for field in _SIMPLE_FIELDS:
        if field in data and getattr(thread, field) != data[field]:
            setattr(thread, field, data[field])
            changed.add(field)

    if "slug" in data and data["slug"] != thread.slug:
        if not is_admin(user):
            raise forbidden()
        if await _slug_exists(db, data["slug"]):
            raise _slug_taken()
        thread.slug = data["slug"]
        changed.add("slug")

    if "body_html" in data:
        html, text = clean_body(data["body_html"])
        if html != thread.body_html:
            thread.body_html, thread.body_text = html, text
            changed.add("body_html")

    if "category_id" in data and data["category_id"] != thread.category_id:
        await _checked_category(db, category_id=data["category_id"], user=user)
        thread.category_id = data["category_id"]
        changed.add("category_id")

    recount: set[int] = set()
    if "tags" in data:
        tags = await get_or_create_tags(db, names=list(data["tags"] or []))
        old_ids = [tag.id for tag in thread.tags]
        if [tag.id for tag in tags] != old_ids:
            recount.update(old_ids)
            recount.update(tag.id for tag in tags)
            thread.tags = list(tags)
            changed.add("tags")

    if "knowbase_links" in data:
        links = link_pairs(data["knowbase_links"] or [])
        current = await crud_links.list_links(
            db, content_type=ContentType.THREAD, content_id=thread.id
        )
        if links != [(link.kb_type, link.kb_id) for link in current]:
            if knowbase is None:
                raise ValueError("knowbase client required to save KNOWBASE links")
            await crud_links.replace_links(
                db,
                content_type=ContentType.THREAD,
                content_id=thread.id,
                links=links,
                knowbase=knowbase,
            )
            changed.add("knowbase_links")

    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if _is_slug_violation(exc):
            raise _slug_taken() from None
        raise
    await recount_tag_usage(db, tag_ids=recount)
    return sorted(changed)


async def soft_delete_thread(
    db: AsyncSession, *, thread: Thread, now: datetime | None = None
) -> Thread:
    """Mark the thread deleted (``status`` + ``deleted_at``) and refresh its tags' counts.
    Its replies stay as they are (they are unreachable through a deleted thread)."""
    thread.status = ContentStatus.DELETED
    thread.deleted_at = now or datetime.now(UTC)
    await db.flush()
    await recount_tag_usage(db, tag_ids=[tag.id for tag in thread.tags])
    return thread


async def set_pinned(db: AsyncSession, *, thread: Thread, pinned: bool) -> bool:
    """Pin or unpin; returns whether anything changed (idempotent)."""
    if thread.is_pinned == pinned:
        return False
    thread.is_pinned = pinned
    await db.flush()
    return True


async def set_locked(db: AsyncSession, *, thread: Thread, locked: bool) -> bool:
    """Lock or unlock (a locked thread takes no replies and no author edits); returns whether
    anything changed (idempotent)."""
    if thread.is_locked == locked:
        return False
    thread.is_locked = locked
    await db.flush()
    return True
