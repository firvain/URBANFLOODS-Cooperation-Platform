"""Attachment (uploaded image) data access. Never commits; the caller (``get_db_tx``) does.

Files on disk are handled by ``services/images.py``. Deleting an upload is a soft delete; only
account deletion (``delete_unreferenced_uploads``), the moderators' purge
(``delete_unused_attachments``) and the orphan sweep (``crud/digest.py``) remove rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, Exists, and_, delete, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Mark the row deleted and clear it as anyone's avatar. The caller removes the files once
    the change is committed."""
    attachment.deleted_at = now or datetime.now(UTC)
    await db.execute(
        update(User)
        .where(User.avatar_attachment_id == attachment.id)
        .values(avatar_attachment_id=None)
    )
    await db.flush()
    return attachment


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


def _mentions_attachment(model: type) -> ColumnElement[bool]:
    """``model.body_html`` contains the attachment's main or thumbnail path (plain substring
    match: ``strpos`` has no wildcards)."""
    return or_(
        func.strpos(model.body_html, Attachment.storage_path) > 0,
        and_(
            Attachment.thumb_path.is_not(None),
            func.strpos(model.body_html, Attachment.thumb_path) > 0,
        ),
    )


def _referenced_in_body(model: type, *where: ColumnElement[bool]) -> Exists:
    """A row of ``model`` (restricted by ``where``, if given) whose ``body_html`` contains the
    attachment's main or thumbnail path."""
    return select(literal(1)).where(_mentions_attachment(model), *where).exists()


def _is_cover(*where: ColumnElement[bool]) -> Exists:
    return select(literal(1)).where(Post.cover_attachment_id == Attachment.id, *where).exists()


def content_usage_conditions() -> list[ColumnElement[bool]]:
    """WHERE clauses (correlated on ``attachments``), any of which is true when content uses the
    attachment: a post cover, or a path in the body of a post, thread, reply or comment, whatever
    its status (deleted content can be restored)."""
    return [_is_cover(), *(_referenced_in_body(model) for model in _BODY_MODELS)]


def unused_attachment_conditions() -> list[ColumnElement[bool]]:
    """WHERE clauses (correlated on ``attachments``) true when nothing uses the attachment: not a
    post cover, not anyone's avatar, and not referenced by path in the body of any post, thread,
    reply or comment, whatever its status (deleted content can be restored)."""
    return [
        ~select(literal(1)).where(User.avatar_attachment_id == Attachment.id).exists(),
        *(~condition for condition in content_usage_conditions()),
    ]


async def is_used_in_content(db: AsyncSession, *, attachment_id: int) -> bool:
    """True when a post cover or any content body (any status) uses the attachment. Being an
    avatar does not count (deleting an avatar clears it)."""
    stmt = select(Attachment.id).where(
        Attachment.id == attachment_id, or_(*content_usage_conditions())
    )
    return (await db.scalar(stmt)) is not None


async def usage_by_attachment(
    db: AsyncSession, *, attachment_ids: Sequence[int]
) -> dict[int, list[ContentUsage]]:
    """``{attachment_id: [usage, ...]}`` for the given attachments (covers and body references
    in content of any status), each list ordered by content type and id without duplicates.
    Attachments nobody uses map to an empty list."""
    ids = list(set(attachment_ids))
    found: dict[int, dict[tuple[ContentType, int], ContentUsage]] = {i: {} for i in ids}
    if not ids:
        return {}
    in_ids = Attachment.id.in_(ids)
    queries = [
        (
            ContentType.POST,
            select(Attachment.id, Post.id, Post.title, Post.slug, Post.status)
            .select_from(Attachment)
            .join(Post, Post.cover_attachment_id == Attachment.id)
            .where(in_ids),
        ),
        (
            ContentType.POST,
            select(Attachment.id, Post.id, Post.title, Post.slug, Post.status)
            .select_from(Attachment)
            .join(Post, _mentions_attachment(Post))
            .where(in_ids),
        ),
        (
            ContentType.THREAD,
            select(Attachment.id, Thread.id, Thread.title, Thread.slug, Thread.status)
            .select_from(Attachment)
            .join(Thread, _mentions_attachment(Thread))
            .where(in_ids),
        ),
        (
            ContentType.REPLY,
            select(Attachment.id, Reply.id, Thread.title, Thread.slug, Reply.status)
            .select_from(Attachment)
            .join(Reply, _mentions_attachment(Reply))
            .join(Thread, Thread.id == Reply.thread_id)
            .where(in_ids),
        ),
        (
            ContentType.COMMENT,
            select(Attachment.id, Comment.id, Post.title, Post.slug, Comment.status)
            .select_from(Attachment)
            .join(Comment, _mentions_attachment(Comment))
            .join(Post, Post.id == Comment.post_id)
            .where(in_ids),
        ),
    ]
    for content_type, stmt in queries:
        for attachment_id, content_id, title, slug, status in (await db.execute(stmt)).all():
            found[attachment_id][(content_type, content_id)] = ContentUsage(
                content_type=content_type,
                id=content_id,
                title=title,
                slug=slug,
                status=status,
            )
    order = list(ContentType)
    return {
        attachment_id: sorted(usages.values(), key=lambda u: (order.index(u.content_type), u.id))
        for attachment_id, usages in found.items()
    }


async def referenced_attachment_ids(
    db: AsyncSession,
    *,
    bodies: Sequence[tuple[type, Sequence[int]]],
    cover_post_ids: Sequence[int] = (),
) -> set[int]:
    """Ids of the attachments (any uploader, deleted ones too) used by the given rows: as the
    cover of one of ``cover_post_ids``, or by path in the body of a ``(model, ids)`` row."""
    conditions: list[ColumnElement[bool]] = []
    if cover_post_ids:
        conditions.append(_is_cover(Post.id.in_(list(cover_post_ids))))
    for model, ids in bodies:
        if ids:
            conditions.append(_referenced_in_body(model, model.id.in_(list(ids))))
    if not conditions:
        return set()
    return set((await db.scalars(select(Attachment.id).where(or_(*conditions)))).all())


async def delete_unused_attachments(
    db: AsyncSession, *, attachment_ids: Iterable[int]
) -> list[tuple[str, str | None]]:
    """Hard-delete those of the given attachments (any uploader) that nothing uses any more
    (see :func:`unused_attachment_conditions`). Returns the ``(storage_path, thumb_path)`` of
    each deleted row; the caller removes the files once the transaction has committed."""
    ids = list(set(attachment_ids))
    if not ids:
        return []
    stmt = (
        delete(Attachment)
        .where(Attachment.id.in_(ids), *unused_attachment_conditions())
        .returning(Attachment.storage_path, Attachment.thumb_path)
        .execution_options(synchronize_session=False)
    )
    return [(row.storage_path, row.thumb_path) for row in (await db.execute(stmt)).all()]


async def delete_unreferenced_uploads(
    db: AsyncSession, *, user_id: int
) -> list[tuple[str, str | None]]:
    """Hard-delete the user's own uploads (soft-deleted ones too) that nothing uses. Used by
    account deletion after anonymisation has cleared the avatar link: contributions stay
    (CC BY 4.0), everything else the member uploaded goes. Other members' uploads are never
    touched.

    Returns the ``(storage_path, thumb_path)`` of each deleted row; the caller removes the files
    once the transaction has committed."""
    stmt = (
        delete(Attachment)
        .where(Attachment.uploader_id == user_id, *unused_attachment_conditions())
        .returning(Attachment.storage_path, Attachment.thumb_path)
        .execution_options(synchronize_session=False)
    )
    return [(row.storage_path, row.thumb_path) for row in (await db.execute(stmt)).all()]
