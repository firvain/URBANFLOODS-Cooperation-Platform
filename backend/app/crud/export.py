"""Read models for the FAIR exports, the Atom feeds and the sitemap (increment 5b).

Public content only: every query uses ``visible_filter(model, None)`` (published rows), and the
nested comments and replies are filtered the same way. Read-only; never commits.

The full exports walk the table in id order with keyset pagination (``id > last id``) in
chunks of :data:`CHUNK_SIZE`, so memory stays bounded and a row inserted mid-export never
shifts the pages. :data:`CHUNK_SIZE` is read at call time (tests shrink it).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, ScalarSelect, Table, func, literal_column, select, union
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.crud.visibility import visible_filter
from app.db.enums import CategoryKind, ContentType
from app.db.models import (
    Category,
    Comment,
    KnowbaseLink,
    Organisation,
    Post,
    Reply,
    Tag,
    Thread,
    User,
    post_tags,
    thread_tags,
)

CHUNK_SIZE = 500
FEED_SIZE = 20


@dataclass(slots=True)
class PostExport:
    post: Post
    links: list[KnowbaseLink] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)


@dataclass(slots=True)
class ThreadExport:
    thread: Thread
    links: list[KnowbaseLink] = field(default_factory=list)
    replies: list[Reply] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    kind: ContentType
    slug: str
    lastmod: datetime


@dataclass(frozen=True, slots=True)
class ExportVersion:
    """Validators for an export: ``etag`` changes whenever a row enters, leaves or changes."""

    etag: str
    last_modified: datetime | None


# --- helpers ----------------------------------------------------------------------------------


def _author_options(relationship: Any) -> Any:
    return joinedload(relationship).joinedload(User.organisation)


def _post_query() -> Any:
    return select(Post).options(
        _author_options(Post.author),
        joinedload(Post.category),
        selectinload(Post.tags),
    )


def _thread_query() -> Any:
    return select(Thread).options(
        _author_options(Thread.author),
        joinedload(Thread.category),
        selectinload(Thread.tags),
    )


async def _links_by_content(
    db: AsyncSession, *, content_type: ContentType, ids: Sequence[int]
) -> dict[int, list[KnowbaseLink]]:
    stmt = (
        select(KnowbaseLink)
        .where(KnowbaseLink.content_type == content_type, KnowbaseLink.content_id.in_(ids))
        .order_by(KnowbaseLink.content_id, KnowbaseLink.sort_order, KnowbaseLink.id)
    )
    grouped: dict[int, list[KnowbaseLink]] = {}
    for link in (await db.scalars(stmt)).all():
        grouped.setdefault(link.content_id, []).append(link)
    return grouped


async def _comments_by_post(db: AsyncSession, ids: Sequence[int]) -> dict[int, list[Comment]]:
    stmt = (
        select(Comment)
        .options(_author_options(Comment.author))
        .where(Comment.post_id.in_(ids), visible_filter(Comment, None))
        .order_by(Comment.post_id, Comment.created_at, Comment.id)
    )
    grouped: dict[int, list[Comment]] = {}
    for comment in (await db.scalars(stmt)).unique().all():
        grouped.setdefault(comment.post_id, []).append(comment)
    return grouped


async def _replies_by_thread(db: AsyncSession, ids: Sequence[int]) -> dict[int, list[Reply]]:
    stmt = (
        select(Reply)
        .options(_author_options(Reply.author))
        .where(Reply.thread_id.in_(ids), visible_filter(Reply, None))
        .order_by(Reply.thread_id, Reply.created_at, Reply.id)
    )
    grouped: dict[int, list[Reply]] = {}
    for reply in (await db.scalars(stmt)).unique().all():
        grouped.setdefault(reply.thread_id, []).append(reply)
    return grouped


# --- full exports -----------------------------------------------------------------------------


async def iter_posts(
    db: AsyncSession, *, with_children: bool = True
) -> AsyncIterator[list[PostExport]]:
    """Every published post in id order, a chunk at a time. With ``with_children`` each comes
    with its KNOWBASE links and published comments (oldest first)."""
    chunk_size = CHUNK_SIZE
    last_id = 0
    while True:
        stmt = (
            _post_query()
            .where(visible_filter(Post, None), Post.id > last_id)
            .order_by(Post.id)
            .limit(chunk_size)
        )
        posts = list((await db.scalars(stmt)).unique().all())
        if not posts:
            return
        ids = [post.id for post in posts]
        links: dict[int, list[KnowbaseLink]] = {}
        comments: dict[int, list[Comment]] = {}
        if with_children:
            links = await _links_by_content(db, content_type=ContentType.POST, ids=ids)
            comments = await _comments_by_post(db, ids)
        yield [
            PostExport(post, links.get(post.id, []), comments.get(post.id, [])) for post in posts
        ]
        if len(posts) < chunk_size:
            return
        last_id = ids[-1]


async def iter_threads(db: AsyncSession) -> AsyncIterator[list[ThreadExport]]:
    """Every published thread in id order, a chunk at a time, each with its KNOWBASE links and
    published replies (oldest first; ``parent_reply_id`` kept as stored)."""
    chunk_size = CHUNK_SIZE
    last_id = 0
    while True:
        stmt = (
            _thread_query()
            .where(visible_filter(Thread, None), Thread.id > last_id)
            .order_by(Thread.id)
            .limit(chunk_size)
        )
        threads = list((await db.scalars(stmt)).unique().all())
        if not threads:
            return
        ids = [thread.id for thread in threads]
        links = await _links_by_content(db, content_type=ContentType.THREAD, ids=ids)
        replies = await _replies_by_thread(db, ids)
        yield [
            ThreadExport(thread, links.get(thread.id, []), replies.get(thread.id, []))
            for thread in threads
        ]
        if len(threads) < chunk_size:
            return
        last_id = ids[-1]


def _stamp(model: Any, *where: ColumnElement[bool]) -> list[ScalarSelect[Any]]:
    """Count and latest ``updated_at`` of ``model``'s rows (a row entering, leaving or changing
    moves one of them; the ORM bumps ``updated_at`` on every update)."""
    return [
        select(func.count()).select_from(model).where(*where).scalar_subquery(),
        select(func.max(model.updated_at)).where(*where).scalar_subquery(),
    ]


def _fingerprint(
    columns: Sequence[ColumnElement[Any]],
    order_by: Sequence[ColumnElement[Any]],
    *where: ColumnElement[bool],
) -> ScalarSelect[Any]:
    """md5 of ``columns`` over the matching rows, for tables without a usable ``updated_at``.

    Each value is ``quote_nullable``-d (``NULL`` or a quoted literal with its quotes doubled), so
    no two different rows give the same text (``concat_ws`` alone skips NULLs: name ``A:3`` with
    no organisation read like name ``A`` with organisation 3).
    """
    row = func.concat_ws(literal_column("','"), *(func.quote_nullable(c) for c in columns))
    joined = func.string_agg(row, aggregate_order_by(literal_column("';'"), *order_by))
    stmt = select(func.md5(func.coalesce(joined, literal_column("''"))))
    return stmt.where(*where).scalar_subquery()


def _exported_authors(models: Sequence[Any]) -> ScalarSelect[Any]:
    """What the export shows of its authors (the authors of its published ``models``): name,
    organisation (its own row is stamped separately) and whether the account was erased. Not
    ``updated_at`` (every sign-in bumps it), and nobody else: a registration or the rename of a
    member with nothing in the export leaves the ETag alone. An erased author keeps their
    content, so stays an author and the erasure is seen."""
    authors = union(
        *(select(model.author_id).where(visible_filter(model, None)) for model in models)
    )
    return _fingerprint(
        [User.id, User.display_name, User.organisation_id, User.deleted_at.is_(None)],
        [User.id],
        User.id.in_(authors),
    )


def _exported_tags(junction: Table, content_key: str) -> list[ScalarSelect[Any]]:
    """Tag names (renames, merges, deletes) and which content carries which tag (a tag-only edit
    does not bump the content's ``updated_at``)."""
    content_id = junction.c[content_key]
    return [
        _fingerprint([Tag.id, Tag.slug, Tag.name], [Tag.id]),
        _fingerprint([content_id, junction.c.tag_id], [content_id, junction.c.tag_id]),
    ]


def _exported_links(content_type: ContentType) -> list[ScalarSelect[Any]]:
    """KNOWBASE links are replaced (deleted and re-inserted), never updated: count and max id."""
    of_type = KnowbaseLink.content_type == content_type
    return [
        select(func.count()).select_from(KnowbaseLink).where(of_type).scalar_subquery(),
        select(func.max(KnowbaseLink.id)).where(of_type).scalar_subquery(),
    ]


async def _version(
    db: AsyncSession,
    models: Sequence[Any],
    *,
    category_kind: CategoryKind,
    junction: Table,
    content_key: str,
    links: ContentType | None = None,
) -> ExportVersion:
    """One query, hashed: the published rows of each content model (count, latest
    ``updated_at``; status changes bump it), and everything else an export shows: their authors
    (renames, erasure), organisations, the categories of its kind, tags and KNOWBASE links.
    ``Last-Modified`` is the latest ``updated_at`` among them."""
    columns: list[ScalarSelect[Any]] = []
    for model in models:
        columns.extend(_stamp(model, visible_filter(model, None)))
    columns.extend(_stamp(Organisation))
    columns.extend(_stamp(Category, Category.kind == category_kind))
    stamped = len(columns)
    columns.append(_exported_authors(models))
    columns.extend(_exported_tags(junction, content_key))
    if links is not None:
        columns.extend(_exported_links(links))
    row = (await db.execute(select(*columns))).one()
    stamps = [value for value in row[1:stamped:2] if value is not None]
    digest = hashlib.sha256("|".join(str(value) for value in row).encode()).hexdigest()[:32]
    return ExportVersion(etag=f'"{digest}"', last_modified=max(stamps) if stamps else None)


async def posts_version(db: AsyncSession) -> ExportVersion:
    """Validators of the posts JSON (posts, their comments and KNOWBASE links)."""
    return await _version(
        db,
        [Post, Comment],
        category_kind=CategoryKind.BLOG,
        junction=post_tags,
        content_key="post_id",
        links=ContentType.POST,
    )


async def posts_csv_version(db: AsyncSession) -> ExportVersion:
    """Validators of the posts CSV (no comments or KNOWBASE links in it)."""
    return await _version(
        db, [Post], category_kind=CategoryKind.BLOG, junction=post_tags, content_key="post_id"
    )


async def threads_version(db: AsyncSession) -> ExportVersion:
    """Validators of the threads export (threads, their replies and KNOWBASE links)."""
    return await _version(
        db,
        [Thread, Reply],
        category_kind=CategoryKind.FORUM,
        junction=thread_tags,
        content_key="thread_id",
        links=ContentType.THREAD,
    )


# --- feeds and sitemap ------------------------------------------------------------------------


async def latest_posts(db: AsyncSession, *, limit: int = FEED_SIZE) -> list[Post]:
    """The newest published posts (by ``published_at``)."""
    stmt = (
        _post_query()
        .where(visible_filter(Post, None))
        .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).unique().all())


async def latest_threads(db: AsyncSession, *, limit: int = FEED_SIZE) -> list[Thread]:
    """The newest published threads (by ``published_at``)."""
    stmt = (
        _thread_query()
        .where(visible_filter(Thread, None))
        .order_by(Thread.published_at.desc().nulls_last(), Thread.id.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).unique().all())


async def sitemap_entries(db: AsyncSession) -> list[SitemapEntry]:
    """Slug and ``updated_at`` of every published post, then every published thread."""
    entries: list[SitemapEntry] = []
    for kind, model in ((ContentType.POST, Post), (ContentType.THREAD, Thread)):
        stmt = (
            select(model.slug, model.updated_at)
            .where(visible_filter(model, None))
            .order_by(model.id)
        )
        entries.extend(
            SitemapEntry(kind, slug, updated_at) for slug, updated_at in (await db.execute(stmt))
        )
    return entries
