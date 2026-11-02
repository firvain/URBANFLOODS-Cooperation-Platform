"""Attachment (uploaded image) data access. Never commits; the caller (``get_db_tx``) does.

Files on disk are handled by ``services/images.py``. Deleting an upload is a soft delete; only
account deletion (``delete_unreferenced_uploads``), the moderators' purge
(``delete_unused_attachments``) and the orphan sweep (``crud/digest.py``) remove rows.

Usage: content uses an attachment when it is a post's cover or when a body really embeds it (an
``<img>`` whose ``src`` is the upload's URL, see :func:`_embeds`); a mere mention of the path is
not a use. Whose content counts is a :class:`UsageScope`: anyone's for the orphan sweep, the
moderators' purge, the uploads panel and an admin's delete (nothing anyone shows is removed
behind their back); only the uploader's own for the uploader's delete, avatar replacement and
account erasure (the uploader owns the image, so another member embedding it cannot keep it).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Exists,
    String,
    and_,
    case,
    delete,
    false,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.enums import ContentStatus, ContentType
from app.db.models import Attachment, Comment, Post, Reply, Thread, User

_BODY_MODELS = (Post, Thread, Reply, Comment)


async def create_attachment(
    db: AsyncSession,
    *,
    uploader_id: int,
    storage_path: str,
    thumb_path: str | None,
    original_filename: str,
    mime: str,
    size_bytes: int,
    width: int,
    height: int,
    alt_text: str,
) -> Attachment:
    attachment = Attachment(
        uploader_id=uploader_id,
        storage_path=storage_path,
        thumb_path=thumb_path,
        original_filename=original_filename,
        mime=mime,
        size_bytes=size_bytes,
        width=width,
        height=height,
        alt_text=alt_text,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment, ["created_at"])
    return attachment


async def get_attachment(db: AsyncSession, *, attachment_id: int) -> Attachment | None:
    """The attachment if it exists and is not deleted."""
    stmt = select(Attachment).where(Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_for_uploader(
    db: AsyncSession, *, user_id: int, skip: int = 0, limit: int = 50
) -> tuple[int, list[Attachment]]:
    """``(total, items)`` of the user's not-deleted attachments, newest first."""
    conditions = (Attachment.uploader_id == user_id, Attachment.deleted_at.is_(None))
    total_stmt = select(func.count()).select_from(
        select(Attachment.id).where(*conditions).subquery()
    )
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = (
        select(Attachment)
        .where(*conditions)
        .order_by(Attachment.created_at.desc(), Attachment.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return total, list((await db.scalars(stmt)).all())


async def soft_delete_attachment(
    db: AsyncSession, *, attachment: Attachment, now: datetime | None = None
) -> Attachment:
    """Mark the row deleted, clear it as anyone's avatar and as the cover of posts its uploader
    did not author (the uploader owns the image; otherwise those posts would point at a deleted
    image and keep the row from the orphan sweep). The uploader's own posts keep the link, as
    their content's images do. The caller removes the files once the change is committed."""
    attachment.deleted_at = now or datetime.now(UTC)
    await db.execute(
        update(User)
        .where(User.avatar_attachment_id == attachment.id)
        .values(avatar_attachment_id=None)
    )
    await db.execute(
        update(Post)
        .where(
            Post.cover_attachment_id == attachment.id,
            Post.author_id.is_distinct_from(attachment.uploader_id),
        )
        .values(cover_attachment_id=None)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return attachment


# First key of the two-int ``pg_advisory_xact_lock`` taken per uploader (the second is the user
# id): a namespace of its own, so it cannot clash with any other advisory lock.
UPLOAD_LOCK_NAMESPACE = 0x55504C44  # "UPLD"


async def lock_uploads_of(db: AsyncSession, *, user_id: int) -> None:
    """Take the transaction-scoped advisory lock on the user's uploads (released at commit or
    rollback). Taken before :func:`count_uploads_today`, it makes the daily cap hold under
    parallel uploads of one member."""
    await db.execute(select(func.pg_advisory_xact_lock(UPLOAD_LOCK_NAMESPACE, user_id)))


async def count_uploads_today(
    db: AsyncSession, *, user_id: int, now: datetime | None = None
) -> int:
    """Attachments the user created since 00:00 UTC today, deleted ones included (deleting does
    not give a slot back)."""
    now = now or datetime.now(UTC)
    midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.count(Attachment.id)).where(
        Attachment.uploader_id == user_id, Attachment.created_at >= midnight
    )
    return (await db.execute(stmt)).scalar_one()


# --- usage ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentUsage:
    """Where an attachment is used. Replies and comments carry the ``title``/``slug`` of the
    thread/post they are shown on (``id`` stays the reply's/comment's own)."""

    content_type: ContentType
    id: int
    title: str | None
    slug: str | None
    status: ContentStatus
    by_uploader: bool  # the content's author is the attachment's uploader


class UsageScope(StrEnum):
    """Whose content counts as using an attachment."""

    ANYONE = "anyone"
    UPLOADER = "uploader"  # only content the attachment's uploader authored


# A real embed as nh3 stores it (``services/sanitize.py``): tag and attribute names lower-case,
# values double-quoted with ``"`` and ``>`` escaped inside them, so ``[^>]*`` stays within the
# tag and a quote inside a value cannot fake a ``src``; text never holds a raw ``<``. The
# ``src`` is the upload's URL, relative or after an absolute http(s) origin (scheme in any
# case), ended by its quote; the URL prefix and the path are matched exactly.
_EMBED_TAG = r'<img\s([^>]*\s)?src="([Hh][Tt][Tt][Pp][Ss]?://[^/"]+)?'
_EMBED_SUFFIX = '"'


def _embed_prefix() -> str:
    """The regex up to the stored path: the ``<img ... src="`` part and the upload URL prefix
    (``UPLOAD_URL_PREFIX``, which builds and serves the URLs) with one trailing slash."""
    return _EMBED_TAG + re.escape(settings.UPLOAD_URL_PREFIX.rstrip("/") + "/")


def _as_regex_literal(path: ColumnElement[str]) -> ColumnElement[str]:
    """``path`` as a Postgres regular expression matching exactly that text: every character
    except letters, digits and ``_`` is backslash-escaped (a literal in ARE syntax)."""
    return func.regexp_replace(path, r"([^[:alnum:]_])", r"\\\1", "g", type_=String)


def _embeds(body: ColumnElement[str], path: ColumnElement[str]) -> ColumnElement[bool]:
    """``body`` has an ``<img>`` whose ``src`` is the upload URL of ``path``. A ``CASE`` makes
    sure the cheap ``strpos`` filter runs first and the regular expression only for bodies that
    contain the path (the planner may reorder the operands of an ``AND``)."""
    pattern = literal(_embed_prefix(), String) + _as_regex_literal(path) + literal(_EMBED_SUFFIX)
    return case(
        (func.strpos(body, path) > 0, body.regexp_match(pattern)),
        else_=false(),
    )


def _embeds_attachment(model: type) -> ColumnElement[bool]:
    """``model.body_html`` embeds the attachment's main image or its thumbnail."""
    return or_(
        _embeds(model.body_html, Attachment.storage_path),
        and_(Attachment.thumb_path.is_not(None), _embeds(model.body_html, Attachment.thumb_path)),
    )


def _scope_conditions(model: type, *, scope: UsageScope, live_only: bool) -> list[Any]:
    """WHERE clauses restricting the rows of ``model`` that count: with
    ``UsageScope.UPLOADER`` those the attachment's uploader authored, with ``live_only`` those
    whose status is not ``deleted``."""
    where: list[Any] = []
    if scope is UsageScope.UPLOADER:
        where.append(model.author_id == Attachment.uploader_id)
    if live_only:
        where.append(model.status != ContentStatus.DELETED)
    return where


def _referenced_in_body(model: type, *where: ColumnElement[bool]) -> Exists:
    """A row of ``model`` (restricted by ``where``, if given) whose ``body_html`` embeds the
    attachment's main image or thumbnail."""
    return select(literal(1)).where(_embeds_attachment(model), *where).exists()


def _is_cover(*where: ColumnElement[bool]) -> Exists:
    return select(literal(1)).where(Post.cover_attachment_id == Attachment.id, *where).exists()


def content_usage_conditions(
    *, scope: UsageScope = UsageScope.ANYONE, live_only: bool = False
) -> list[ColumnElement[bool]]:
    """WHERE clauses (correlated on ``attachments``), any of which is true when content uses the
    attachment: a post cover, or a real embed in the body of a post, thread, reply or comment,
    whatever its status (deleted content can be restored). ``scope`` chooses whose content
    counts; ``live_only`` leaves out content whose status is ``deleted``."""
    return [
        _is_cover(*_scope_conditions(Post, scope=scope, live_only=live_only)),
        *(
            _referenced_in_body(model, *_scope_conditions(model, scope=scope, live_only=live_only))
            for model in _BODY_MODELS
        ),
    ]


def unused_attachment_conditions(
    *, scope: UsageScope = UsageScope.ANYONE
) -> list[ColumnElement[bool]]:
    """WHERE clauses (correlated on ``attachments``) true when nothing uses the attachment: not
    anyone's avatar, not a post cover and not embedded in the body of any post, thread, reply or
    comment of ``scope``, whatever its status (deleted content can be restored)."""
    return [
        ~select(literal(1)).where(User.avatar_attachment_id == Attachment.id).exists(),
        *(~condition for condition in content_usage_conditions(scope=scope)),
    ]


async def is_used_in_content(
    db: AsyncSession,
    *,
    attachment_id: int,
    scope: UsageScope = UsageScope.ANYONE,
    live_only: bool = False,
) -> bool:
    """True when content of ``scope`` uses the attachment as a post cover or embeds it in a body
    (any status, or with ``live_only`` any status but ``deleted``). Being an avatar does not
    count (deleting an avatar clears it)."""
    stmt = select(Attachment.id).where(
        Attachment.id == attachment_id,
        or_(*content_usage_conditions(scope=scope, live_only=live_only)),
    )
    return (await db.scalar(stmt)) is not None


async def usage_by_attachment(
    db: AsyncSession, *, attachment_ids: Sequence[int]
) -> dict[int, list[ContentUsage]]:
    """``{attachment_id: [usage, ...]}`` for the given attachments (covers and real embeds in
    anyone's content, any status, each saying whether the attachment's uploader authored it),
    each list ordered by content type and id without duplicates.
    Attachments nobody uses map to an empty list."""
    ids = list(set(attachment_ids))
    found: dict[int, dict[tuple[ContentType, int], ContentUsage]] = {i: {} for i in ids}
    if not ids:
        return {}
    in_ids = Attachment.id.in_(ids)
    queries = [
        (
            ContentType.POST,
            select(
                Attachment.id,
                Post.id,
                Post.title,
                Post.slug,
                Post.status,
                Post.author_id == Attachment.uploader_id,
            )
            .select_from(Attachment)
            .join(Post, Post.cover_attachment_id == Attachment.id)
            .where(in_ids),
        ),
        (
            ContentType.POST,
            select(
                Attachment.id,
                Post.id,
                Post.title,
                Post.slug,
                Post.status,
                Post.author_id == Attachment.uploader_id,
            )
            .select_from(Attachment)
            .join(Post, _embeds_attachment(Post))
            .where(in_ids),
        ),
        (
            ContentType.THREAD,
            select(
                Attachment.id,
                Thread.id,
                Thread.title,
                Thread.slug,
                Thread.status,
                Thread.author_id == Attachment.uploader_id,
            )
            .select_from(Attachment)
            .join(Thread, _embeds_attachment(Thread))
            .where(in_ids),
        ),
        (
            ContentType.REPLY,
            select(
                Attachment.id,
                Reply.id,
                Thread.title,
                Thread.slug,
                Reply.status,
                Reply.author_id == Attachment.uploader_id,
            )
            .select_from(Attachment)
            .join(Reply, _embeds_attachment(Reply))
            .join(Thread, Thread.id == Reply.thread_id)
            .where(in_ids),
        ),
        (
            ContentType.COMMENT,
            select(
                Attachment.id,
                Comment.id,
                Post.title,
                Post.slug,
                Comment.status,
                Comment.author_id == Attachment.uploader_id,
            )
            .select_from(Attachment)
            .join(Comment, _embeds_attachment(Comment))
            .join(Post, Post.id == Comment.post_id)
            .where(in_ids),
        ),
    ]
    for content_type, stmt in queries:
        rows = (await db.execute(stmt)).all()
        for attachment_id, content_id, title, slug, status, by_uploader in rows:
            found[attachment_id][(content_type, content_id)] = ContentUsage(
                content_type=content_type,
                id=content_id,
                title=title,
                slug=slug,
                status=status,
                by_uploader=bool(by_uploader),  # NULL (no author or uploader) is not theirs
            )
    order = list(ContentType)
    return {
        attachment_id: sorted(usages.values(), key=lambda u: (order.index(u.content_type), u.id))
        for attachment_id, usages in found.items()
    }


async def referenced_attachment_ids(
    db: AsyncSession,
    *,
    bodies: Sequence[tuple[type, ColumnElement[bool]]],
    cover_of: ColumnElement[bool] | None = None,
) -> set[int]:
    """Ids of the attachments (any uploader, deleted ones too) used by the given rows: as the
    cover of a post matching ``cover_of``, or embedded in the body of a row of ``model``
    matching its condition, for each ``(model, condition)`` in ``bodies``."""
    conditions: list[ColumnElement[bool]] = [
        _referenced_in_body(model, where) for model, where in bodies
    ]
    if cover_of is not None:
        conditions.append(_is_cover(cover_of))
    if not conditions:
        return set()
    return set((await db.scalars(select(Attachment.id).where(or_(*conditions)))).all())


@dataclass(frozen=True)
class DeletedAttachment:
    id: int
    uploader_id: int | None
    storage_path: str
    thumb_path: str | None


async def delete_unused_attachments(
    db: AsyncSession, *, attachment_ids: Iterable[int]
) -> list[DeletedAttachment]:
    """Hard-delete those of the given attachments (any uploader) that nothing uses any more
    (see :func:`unused_attachment_conditions`) and return them, ordered by id; the caller
    removes the files once the transaction has committed."""
    ids = list(set(attachment_ids))
    if not ids:
        return []
    stmt = (
        delete(Attachment)
        .where(Attachment.id.in_(ids), *unused_attachment_conditions())
        .returning(
            Attachment.id, Attachment.uploader_id, Attachment.storage_path, Attachment.thumb_path
        )
        .execution_options(synchronize_session=False)
    )
    rows = (await db.execute(stmt)).all()
    return sorted(
        (
            DeletedAttachment(
                id=row.id,
                uploader_id=row.uploader_id,
                storage_path=row.storage_path,
                thumb_path=row.thumb_path,
            )
            for row in rows
        ),
        key=lambda a: a.id,
    )


async def delete_unreferenced_uploads(
    db: AsyncSession, *, user_id: int
) -> list[tuple[str, str | None]]:
    """Hard-delete the user's own uploads (soft-deleted ones too) that the user's own content
    does not use (not a cover of their post, not embedded in their body, any status) and that
    are nobody's avatar. Used by account deletion after anonymisation has cleared the avatar
    link: contributions stay with their images (CC BY 4.0), everything else the member uploaded
    goes, even if another member embeds it. Other members' uploads are never touched.

    Returns the ``(storage_path, thumb_path)`` of each deleted row; the caller removes the files
    once the transaction has committed."""
    stmt = (
        delete(Attachment)
        .where(
            Attachment.uploader_id == user_id,
            *unused_attachment_conditions(scope=UsageScope.UPLOADER),
        )
        .returning(Attachment.storage_path, Attachment.thumb_path)
        .execution_options(synchronize_session=False)
    )
    return [(row.storage_path, row.thumb_path) for row in (await db.execute(stmt)).all()]
