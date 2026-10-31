"""Attachment (uploaded image) data access. Never commits; the caller (``get_db_tx``) does.

Files on disk are handled by ``services/images.py``. Deleting an upload is a soft delete; only
account deletion (``delete_unreferenced_uploads``) and the orphan sweep (``crud/digest.py``)
remove rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, Exists, and_, delete, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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


def _referenced_in_body(model: type) -> Exists:
    """A row of ``model`` whose ``body_html`` contains the attachment's main or thumbnail path
    (plain substring match: ``strpos`` has no wildcards)."""
    return (
        select(literal(1))
        .where(
            or_(
                func.strpos(model.body_html, Attachment.storage_path) > 0,
                and_(
                    Attachment.thumb_path.is_not(None),
                    func.strpos(model.body_html, Attachment.thumb_path) > 0,
                ),
            )
        )
        .exists()
    )


def unused_attachment_conditions() -> list[ColumnElement[bool]]:
    """WHERE clauses (correlated on ``attachments``) true when nothing uses the attachment: not a
    post cover, not anyone's avatar, and not referenced by path in the body of any post, thread,
    reply or comment, whatever its status (deleted content can be restored)."""
    return [
        ~select(literal(1)).where(Post.cover_attachment_id == Attachment.id).exists(),
        ~select(literal(1)).where(User.avatar_attachment_id == Attachment.id).exists(),
        *(~_referenced_in_body(model) for model in _BODY_MODELS),
    ]


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
