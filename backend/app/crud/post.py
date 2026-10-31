"""Blog post data access: list (visibility, filters, search, sort), detail, create, update and
soft delete, and KNOWBASE mentions. Never commits; the caller (``get_db_tx``) does.

Every read goes through :func:`app.crud.visibility.visible_filter`. Bodies are sanitised here
(``services/sanitize.py``) before they are stored. Status on create follows the trust model:
trusted members and admins publish immediately, everyone else's post is ``pending``. Moderation
transitions (approve, reject, hide, restore) are not part of this module (increment 4b).
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
from app.crud.attachment import get_attachment
from app.crud.tag import get_or_create_tags, recount_tag_usage
from app.crud.visibility import is_admin, is_visible, visible_filter
from app.db.enums import CategoryKind, ContentStatus, ContentType, KbType
from app.db.models import Category, KnowbaseLink, Post, Tag, User
from app.services.knowbase import KnowbaseClient
from app.services.sanitize import excerpt as make_excerpt
from app.services.sanitize import html_to_text, sanitize_html
from app.services.slugs import slugify_title, unique_slug_async

PostSort = Literal["newest", "oldest", "events"]
SLUG_UNIQUE_CONSTRAINT = "uq_posts_slug"
SLUG_INSERT_TRIES = 3
FTS_CONFIG = literal_column("'english'::regconfig")
UPDATABLE_FIELDS = frozenset(
    {
        "title",
        "body_html",
        "excerpt",
        "category_id",
        "cover_attachment_id",
        "locale",
        "event_at",
        "event_url",
        "tags",
        "knowbase_links",
        "slug",
    }
)
# Plain column fields copied as-is when they change.
_SIMPLE_FIELDS = ("title", "locale", "event_at", "event_url")


# --- errors -----------------------------------------------------------------------------------


def not_found() -> AppError:
    return AppError(404, "posts.not_found", "Post not found.")


def forbidden() -> AppError:
    return AppError(403, "posts.forbidden", "You cannot change this post.")


def _slug_taken() -> AppError:
    return AppError(409, "posts.slug_taken", "A post with this slug exists.")


# --- reads ------------------------------------------------------------------------------------


def _with_relations(stmt: Any) -> Any:
    """Eager loads for summaries and details: many-to-one joined, tags by selectin."""
    return stmt.options(
        joinedload(Post.author).joinedload(User.organisation),
        joinedload(Post.author).joinedload(User.avatar),
        joinedload(Post.category),
        joinedload(Post.cover),
        selectinload(Post.tags),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _newest() -> tuple[Any, ...]:
    return (Post.published_at.desc().nulls_last(), Post.created_at.desc(), Post.id.desc())


async def _page(
    db: AsyncSession,
    *,
    conditions: Sequence[ColumnElement[bool]],
    order: Sequence[Any],
    skip: int,
    limit: int,
) -> tuple[int, list[Post]]:
    total_stmt = select(func.count()).select_from(select(Post.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = _with_relations(select(Post).where(*conditions).order_by(*order))
    rows = await db.scalars(stmt.offset(skip).limit(limit))
    return total, list(rows.unique().all())


async def list_posts(
    db: AsyncSession,
    *,
    user: User | None,
    q: str | None = None,
    category_slug: str | None = None,
    tag_slug: str | None = None,
    author_id: int | None = None,
    locale: str | None = None,
    status: ContentStatus | None = None,
    sort: PostSort | None = None,
    upcoming_only: bool = False,
    skip: int = 0,
    limit: int = 20,
    now: datetime | None = None,
) -> tuple[int, list[Post]]:
    """``(total, posts)`` visible to ``user``.

    ``q`` matches the full-text vector (``plainto_tsquery('english')``) or a title substring and,
    unless another ``sort`` is asked for, orders by ``ts_rank``. ``status`` is honoured for admins
    only. ``sort="events"`` keeps posts with an event, soonest first; ``upcoming_only`` keeps
    events from ``now`` on. The default order is newest published first.
    """
    conditions: list[ColumnElement[bool]] = [visible_filter(Post, user)]
    if status is not None and is_admin(user):
        conditions.append(Post.status == status)
    if category_slug:
        conditions.append(
            Post.category_id.in_(
                select(Category.id).where(
                    Category.kind == CategoryKind.BLOG, Category.slug == category_slug
                )
            )
        )
    if tag_slug:
        conditions.append(Post.tags.any(Tag.slug == tag_slug))
    if author_id is not None:
        conditions.append(Post.author_id == author_id)
    if locale:
        conditions.append(Post.locale == locale)
    if sort == "events":
        conditions.append(Post.event_at.is_not(None))
    if upcoming_only:
        conditions.append(Post.event_at >= (now or datetime.now(UTC)))

    order: tuple[Any, ...] = _newest()
    if sort == "oldest":
        order = (Post.published_at.asc().nulls_last(), Post.created_at.asc(), Post.id.asc())
    elif sort == "events":
        order = (Post.event_at.asc(), Post.id.asc())
    query = (q or "").strip()
    if query:
        tsquery = func.plainto_tsquery(FTS_CONFIG, query)
        conditions.append(
            or_(
                Post.fts.bool_op("@@")(tsquery),
                Post.title.ilike(f"%{_escape_like(query)}%", escape="\\"),
            )
        )
        if sort is None:
            order = (func.ts_rank(Post.fts, tsquery).desc(), *_newest())
    return await _page(db, conditions=conditions, order=order, skip=skip, limit=limit)


async def get_post_by_slug(db: AsyncSession, *, slug: str, user: User | None) -> Post | None:
    """The post with ``slug`` if ``user`` may see it."""
    stmt = _with_relations(select(Post).where(Post.slug == slug, visible_filter(Post, user)))
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_post_by_id(db: AsyncSession, *, post_id: int) -> Post | None:
    """The post (any status), relations loaded and refreshed from the database."""
    stmt = _with_relations(select(Post).where(Post.id == post_id)).execution_options(
        populate_existing=True
    )
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_editable_post(db: AsyncSession, *, post_id: int, user: User) -> Post:
    """The post ``user`` may edit or delete: its author while it is not deleted, or an admin.

    Raises 404 ``posts.not_found`` when the post does not exist or ``user`` cannot see it (a
    deleted post counts as gone, for admins too), 403 ``posts.forbidden`` otherwise.
    """
    post = await get_post_by_id(db, post_id=post_id)
    if post is None or post.status == ContentStatus.DELETED or not is_visible(post, user):
        raise not_found()
    if post.author_id != user.id and not is_admin(user):
        raise forbidden()
    return post


def _mentions_condition(kb_type: KbType, kb_id: int) -> ColumnElement[bool]:
    return exists().where(
        KnowbaseLink.content_type == ContentType.POST,
        KnowbaseLink.content_id == Post.id,
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
) -> tuple[int, list[Post]]:
    """``(total, posts)`` linking the KNOWBASE item and visible to ``user``, newest first."""
    conditions = [visible_filter(Post, user), _mentions_condition(kb_type, kb_id)]
    return await _page(db, conditions=conditions, order=_newest(), skip=skip, limit=limit)


async def count_mentions(
    db: AsyncSession, *, kb_type: KbType, kb_id: int, user: User | None
) -> int:
    stmt = select(func.count(Post.id)).where(
        visible_filter(Post, user), _mentions_condition(kb_type, kb_id)
    )
    return (await db.execute(stmt)).scalar_one()


# --- validation helpers -----------------------------------------------------------------------


def _clean_body(body_html: str) -> tuple[str, str]:
    """``(sanitised html, plain text)``; 422 ``{"body_html": "empty"}`` if nothing remains."""
    html = sanitize_html(body_html)
    if not html:
        raise validation_error({"body_html": "empty"})
    return html, html_to_text(html)


def _excerpt_for(given: str | None, text: str) -> str:
    given = " ".join((given or "").split())
    return given or make_excerpt(text)


async def _checked_category(db: AsyncSession, *, category_id: int, user: User) -> Category:
    """A blog category ``user`` may post in. 422 ``category_id`` = ``not_found`` / ``invalid``
    (not a blog category) / ``archived``; 403 ``posts.category_admin_only``."""
    category = await db.get(Category, category_id)
    if category is None:
        raise validation_error({"category_id": "not_found"})
    if category.kind != CategoryKind.BLOG:
        raise validation_error({"category_id": "invalid"})
    if category.is_archived:
        raise validation_error({"category_id": "archived"})
    if category.admin_only and not is_admin(user):
        raise AppError(
            403, "posts.category_admin_only", "Only administrators can post in this category."
        )
    return category


async def _check_cover(
    db: AsyncSession, *, attachment_id: int | None, owner_ids: set[int | None]
) -> None:
    """The cover must be a live attachment uploaded by one of ``owner_ids``; else 422
    ``{"cover_attachment_id": "invalid"}``."""
    if attachment_id is None:
        return
    attachment = await get_attachment(db, attachment_id=attachment_id)
    if (
        attachment is None
        or attachment.uploader_id is None
        or (attachment.uploader_id not in owner_ids)
    ):
        raise validation_error({"cover_attachment_id": "invalid"})


async def _slug_exists(db: AsyncSession, slug: str) -> bool:
    return bool((await db.execute(select(exists().where(Post.slug == slug)))).scalar_one())


def _link_pairs(links: Sequence[Any]) -> list[tuple[KbType, int]]:
    """``[(kb_type, kb_id)]`` from dicts, objects with attributes, or pairs."""
    pairs: list[tuple[KbType, int]] = []
    for link in links:
        if isinstance(link, Mapping):
            pairs.append((KbType(link["kb_type"]), int(link["kb_id"])))
        elif isinstance(link, tuple):
            pairs.append((KbType(link[0]), int(link[1])))
        else:
            pairs.append((KbType(link.kb_type), int(link.kb_id)))
    return pairs


def _is_slug_violation(exc: IntegrityError) -> bool:
    return SLUG_UNIQUE_CONSTRAINT in str(exc.orig)


# --- writes -----------------------------------------------------------------------------------


async def create_post(
    db: AsyncSession,
    *,
    author: User,
    category_id: int,
    title: str,
    body_html: str,
    excerpt: str | None = None,
    cover_attachment_id: int | None = None,
    locale: str = "en",
    event_at: datetime | None = None,
    event_url: str | None = None,
    tag_names: Sequence[str] = (),
    knowbase_links: Sequence[Any] = (),
    knowbase: KnowbaseClient | None = None,
    now: datetime | None = None,
) -> Post:
    """Insert a post and return it with its relations loaded.

    Status: ``published`` (with ``published_at = now``) for trusted members and admins, else
    ``pending``. Raises 422 for an empty body, a bad category or cover, invalid tags or unknown
    KNOWBASE items; 403 ``posts.category_admin_only``; 503 when the KNOWBASE is down.
    """
    now = now or datetime.now(UTC)
    html, text = _clean_body(body_html)
    await _checked_category(db, category_id=category_id, user=author)
    await _check_cover(db, attachment_id=cover_attachment_id, owner_ids={author.id})
    links = _link_pairs(knowbase_links)
    if len(links) > crud_links.MAX_LINKS:
        raise validation_error({"knowbase_links": "too_many"})
    tags = await get_or_create_tags(db, names=list(tag_names))

    publish = author.trusted_at is not None or is_admin(author)
    base = slugify_title(title)
    for attempt in range(SLUG_INSERT_TRIES):
        post = Post(
            author_id=author.id,
            category_id=category_id,
            title=title,
            slug=await unique_slug_async(base, lambda s: _slug_exists(db, s)),
            body_html=html,
            body_text=text,
            excerpt=_excerpt_for(excerpt, text),
            cover_attachment_id=cover_attachment_id,
            locale=locale,
            event_at=event_at,
            event_url=event_url,
            status=ContentStatus.PUBLISHED if publish else ContentStatus.PENDING,
            published_at=now if publish else None,
        )
        try:
            # begin_nested() flushes first: attach the tags only once the post is in the session.
            async with db.begin_nested():
                db.add(post)
                post.tags = list(tags)
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
            content_type=ContentType.POST,
            content_id=post.id,
            links=links,
            knowbase=knowbase,
        )
    await recount_tag_usage(db, tag_ids=[tag.id for tag in tags])
    loaded = await get_post_by_id(db, post_id=post.id)
    assert loaded is not None
    return loaded


async def update_post(
    db: AsyncSession,
    *,
    post: Post,
    user: User,
    data: Mapping[str, Any],
    knowbase: KnowbaseClient | None = None,
) -> list[str]:
    """Apply the fields present in ``data`` (a partial update) and return the sorted names of
    those that changed. The status never changes here. Bodies are re-sanitised; an automatic
    excerpt follows the body unless the excerpt was written by hand. Only admins may change the
    slug (403 ``posts.forbidden``; 409 ``posts.slug_taken``).
    """
    unknown = set(data) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"not post fields: {sorted(unknown)}")
    changed: set[str] = set()

    for field in _SIMPLE_FIELDS:
        if field in data and getattr(post, field) != data[field]:
            setattr(post, field, data[field])
            changed.add(field)

    if "slug" in data and data["slug"] != post.slug:
        if not is_admin(user):
            raise forbidden()
        if await _slug_exists(db, data["slug"]):
            raise _slug_taken()
        post.slug = data["slug"]
        changed.add("slug")

    if "body_html" in data:
        html, text = _clean_body(data["body_html"])
        if html != post.body_html:
            if "excerpt" not in data and post.excerpt == make_excerpt(post.body_text):
                post.excerpt = make_excerpt(text)
            post.body_html, post.body_text = html, text
            changed.add("body_html")

    if "excerpt" in data:
        new_excerpt = _excerpt_for(data["excerpt"], post.body_text)
        if new_excerpt != post.excerpt:
            post.excerpt = new_excerpt
            changed.add("excerpt")

    if "category_id" in data and data["category_id"] != post.category_id:
        await _checked_category(db, category_id=data["category_id"], user=user)
        post.category_id = data["category_id"]
        changed.add("category_id")

    if "cover_attachment_id" in data and data["cover_attachment_id"] != post.cover_attachment_id:
        await _check_cover(
            db, attachment_id=data["cover_attachment_id"], owner_ids={post.author_id, user.id}
        )
        post.cover_attachment_id = data["cover_attachment_id"]
        changed.add("cover_attachment_id")

    recount: set[int] = set()
    if "tags" in data:
        tags = await get_or_create_tags(db, names=list(data["tags"] or []))
        old_ids = [tag.id for tag in post.tags]
        if [tag.id for tag in tags] != old_ids:
            recount.update(old_ids)
            recount.update(tag.id for tag in tags)
            post.tags = list(tags)
            changed.add("tags")

    if "knowbase_links" in data:
        links = _link_pairs(data["knowbase_links"] or [])
        current = await crud_links.list_links(db, content_type=ContentType.POST, content_id=post.id)
        if links != [(link.kb_type, link.kb_id) for link in current]:
            if knowbase is None:
                raise ValueError("knowbase client required to save KNOWBASE links")
            await crud_links.replace_links(
                db,
                content_type=ContentType.POST,
                content_id=post.id,
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


async def soft_delete_post(db: AsyncSession, *, post: Post, now: datetime | None = None) -> Post:
    """Mark the post deleted (``status`` + ``deleted_at``) and refresh its tags' counts."""
    post.status = ContentStatus.DELETED
    post.deleted_at = now or datetime.now(UTC)
    await db.flush()
    await recount_tag_usage(db, tag_ids=[tag.id for tag in post.tags])
    return post
