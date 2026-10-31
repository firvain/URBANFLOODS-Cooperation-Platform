"""Admin moderation: the pending queue, the content actions and the audit log.

Every route needs an admin. Actions load the content row ``FOR UPDATE`` and hand it to
``crud/moderation.py``, which enforces the state machine (409 ``moderation.invalid_transition``)
and writes the ``moderation.<action>`` audit row; unknown content is 404
``moderation.content_not_found``. ``purge`` is outside the state machine: it hard-deletes the item
from any status (files of the attachments it frees are removed after the response).

Approve, reject and an unhide that approves a rejected post/thread email the author
(``services/notifications.py``) from a background task, i.e. after the commit.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Path, Query

from app.api.v1.schemas.moderation import (
    EXCERPT_LENGTH,
    AuditLogEntry,
    AuditLogPage,
    ModerationQueue,
    ModerationReason,
    ModerationResult,
    PurgeResultOut,
    QueueAuthor,
    QueueCategory,
    QueueItem,
)
from app.core.config import settings
from app.core.deps import AdminUser, DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import moderation
from app.db.enums import ContentType
from app.db.models import User
from app.services import images, notifications

router = APIRouter()

# Replies and comments have BIGINT ids.
MAX_ID = 2**63 - 1

ContentId = Annotated[int, Path(ge=1, le=MAX_ID)]
OptionalReason = Annotated[ModerationReason | None, Body()]


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


ACTION_ERRORS = _error_responses(401, 403, 404, 409, 422)


def _queue_author(user: User | None) -> QueueAuthor | None:
    if user is None:
        return None
    return QueueAuthor(
        id=user.id, display_name=user.display_name, trusted=user.trusted_at is not None
    )


async def _load(db: DbTx, content_type: ContentType, content_id: int) -> moderation.ContentModel:
    # ``get_content`` answers None for a post/thread id beyond the INTEGER range.
    content = await moderation.get_content(
        db, content_type=content_type, content_id=content_id, for_update=True
    )
    if content is None:
        raise AppError(404, "moderation.content_not_found", "Content not found.")
    return content


def _result(content: moderation.ContentModel) -> ModerationResult:
    author = content.author
    return ModerationResult(
        content_type=moderation.content_type_of(content),
        id=content.id,
        status=content.status,
        hidden_reason=content.hidden_reason,
        published_at=getattr(content, "published_at", None),
        deleted_at=content.deleted_at,
        author_trusted=author is not None and author.trusted_at is not None,
    )


def _reason(body: ModerationReason | None) -> str | None:
    return body.reason if body is not None else None


def _notify_decision(
    background: BackgroundTasks,
    content: moderation.ContentModel,
    decision: notifications.Decision,
    *,
    admin: User,
    newly_trusted: bool = False,
) -> None:
    """Email the author about ``decision`` after the response (so after the commit); an admin
    deciding on their own content gets no email."""
    background.add_task(
        notifications.send_moderation_decision,
        moderation.content_type_of(content),
        content.id,
        decision,
        newly_trusted,
        actor_id=admin.id,
    )


# --- queue and log ----------------------------------------------------------------------------


@router.get("/queue/", response_model=ModerationQueue, responses=_error_responses(401, 403, 422))
async def moderation_queue(
    admin: AdminUser,
    db: DbTx,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ModerationQueue:
    """Pending posts and threads, oldest first."""
    total, items = await moderation.list_pending(db, skip=skip, limit=limit)
    return ModerationQueue(
        total=total,
        items=[
            QueueItem(
                content_type=content_type,
                id=obj.id,
                title=obj.title,
                slug=obj.slug,
                excerpt=obj.body_text[:EXCERPT_LENGTH],
                locale=obj.locale,
                author=_queue_author(obj.author),
                category=QueueCategory.model_validate(obj.category),
                created_at=obj.created_at,
            )
            for content_type, obj in items
        ],
    )


@router.get("/log/", response_model=AuditLogPage, responses=_error_responses(401, 403, 422))
async def moderation_log(
    admin: AdminUser,
    db: DbTx,
    action: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    actor_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    target_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditLogPage:
    """Audit rows, newest first. ``action`` ending in ``.`` is a prefix (``moderation.``);
    otherwise it is matched exactly. ``actor`` is null for automatic actions."""
    total, rows = await crud_audit.list_actions(
        db, action=action, actor_id=actor_id, target_type=target_type, skip=skip, limit=limit
    )
    return AuditLogPage(total=total, items=[AuditLogEntry.model_validate(row) for row in rows])


# --- actions ----------------------------------------------------------------------------------


@router.post(
    "/{content_type}/{content_id}/approve",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def approve_content(
    content_type: ContentType,
    content_id: ContentId,
    admin: AdminUser,
    db: DbTx,
    background: BackgroundTasks,
) -> ModerationResult:
    """Publish a pending post or thread; its author becomes trusted and is emailed."""
    content = await _load(db, content_type, content_id)
    approval = await moderation.approve(db, content=content, actor=admin)
    _notify_decision(
        background, content, "approved", admin=admin, newly_trusted=approval.newly_trusted
    )
    return _result(content)


@router.post(
    "/{content_type}/{content_id}/reject",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def reject_content(
    content_type: ContentType,
    content_id: ContentId,
    admin: AdminUser,
    db: DbTx,
    background: BackgroundTasks,
    body: OptionalReason = None,
) -> ModerationResult:
    """Hide a pending post or thread as rejected; the optional reason is audited (it is not in
    the email to the author)."""
    content = await _load(db, content_type, content_id)
    await moderation.reject(db, content=content, actor=admin, reason=_reason(body))
    _notify_decision(background, content, "rejected", admin=admin)
    return _result(content)


@router.post(
    "/{content_type}/{content_id}/hide",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def hide_content(
    content_type: ContentType,
    content_id: ContentId,
    admin: AdminUser,
    db: DbTx,
    body: OptionalReason = None,
) -> ModerationResult:
    """Hide published content; the optional reason is audited."""
    content = await _load(db, content_type, content_id)
    return _result(await moderation.hide(db, content=content, actor=admin, reason=_reason(body)))


@router.post(
    "/{content_type}/{content_id}/unhide",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def unhide_content(
    content_type: ContentType,
    content_id: ContentId,
    admin: AdminUser,
    db: DbTx,
    background: BackgroundTasks,
) -> ModerationResult:
    """Publish hidden content again (unhiding a rejected post or thread approves it, and its
    author is emailed)."""
    content = await _load(db, content_type, content_id)
    result = await moderation.unhide(db, content=content, actor=admin)
    if result.approved:
        _notify_decision(
            background, content, "approved", admin=admin, newly_trusted=result.newly_trusted
        )
    return _result(content)


@router.post(
    "/{content_type}/{content_id}/delete",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def delete_content(
    content_type: ContentType, content_id: ContentId, admin: AdminUser, db: DbTx
) -> ModerationResult:
    """Soft-delete content."""
    content = await _load(db, content_type, content_id)
    return _result(await moderation.delete(db, content=content, actor=admin))


@router.post(
    "/{content_type}/{content_id}/restore",
    response_model=ModerationResult,
    responses=ACTION_ERRORS,
)
async def restore_content(
    content_type: ContentType, content_id: ContentId, admin: AdminUser, db: DbTx
) -> ModerationResult:
    """Restore deleted content (to pending if it was never approved)."""
    content = await _load(db, content_type, content_id)
    return _result(await moderation.restore(db, content=content, actor=admin))


@router.post(
    "/{content_type}/{content_id}/purge",
    response_model=PurgeResultOut,
    responses=_error_responses(401, 403, 404, 422),
)
async def purge_content(
    content_type: ContentType,
    content_id: ContentId,
    admin: AdminUser,
    db: DbTx,
    background: BackgroundTasks,
) -> PurgeResultOut:
    """Delete content permanently, from any status: with its comments or replies, its tag and
    KNOWBASE links, and the images nothing else uses; its open reports are resolved."""
    content = await _load(db, content_type, content_id)
    result = await moderation.purge(db, content=content, actor=admin)
    for storage_path, thumb_path in result.files:
        # After the response, so after the commit (``get_db_tx``).
        background.add_task(images.delete_files, settings.UPLOAD_DIR, storage_path, thumb_path)
    return PurgeResultOut.model_validate(result)
