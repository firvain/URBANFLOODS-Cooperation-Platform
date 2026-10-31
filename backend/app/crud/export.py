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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.crud.visibility import visible_filter
from app.db.enums import ContentType
from app.db.models import Comment, KnowbaseLink, Post, Reply, Thread, User

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


async def _version(db: AsyncSession, *models: Any) -> ExportVersion:
    """Count and latest ``updated_at`` of the published rows of each model, hashed. A row that
    is published, changed, hidden or deleted moves a count or a timestamp (status changes bump
    ``updated_at``), so the ETag changes."""
    columns = []
    for model in models:
        published = visible_filter(model, None)
        columns.append(select(func.count()).select_from(model).where(published).scalar_subquery())
        columns.append(select(func.max(model.updated_at)).where(published).scalar_subquery())
    row = (await db.execute(select(*columns))).one()
    stamps = [value for value in row[1::2] if value is not None]
    digest = hashlib.sha256("|".join(str(value) for value in row).encode()).hexdigest()[:32]
    return ExportVersion(etag=f'"{digest}"', last_modified=max(stamps) if stamps else None)


async def posts_version(db: AsyncSession) -> ExportVersion:
    """Validators of the posts exports (posts and their comments)."""
    return await _version(db, Post, Comment)


async def posts_csv_version(db: AsyncSession) -> ExportVersion:
    """Validators of the posts CSV (no comments in it)."""
    return await _version(db, Post)


async def threads_version(db: AsyncSession) -> ExportVersion:
    """Validators of the threads export (threads and their replies)."""
    return await _version(db, Thread, Reply)


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
