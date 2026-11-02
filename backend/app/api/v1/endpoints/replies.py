"""Replies on forum threads: public list (when the thread is visible; one level of nesting),
create (verified, rate limited, 423 on a locked thread), edit (author within 24 h while the
thread is unlocked, or an admin) and soft delete (author or admin; children survive).

Mounted at the API root: ``/threads/{thread_id}/replies/`` and ``/replies/{reply_id}``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.api.v1.params import BigPathId, PathId
from app.api.v1.schemas.reply import (
    PaginatedReplies,
    ReplyCreate,
    ReplyOut,
    ReplyUpdate,
    paginated_replies,
)
from app.core.deps import CurrentUser, DbTx, VerifiedUser
from app.core.exceptions import error_body
from app.core.rate_limit import limit
from app.crud import audit as crud_audit
from app.crud import reply as crud_reply
from app.db.models import Reply
from app.services import notifications

router = APIRouter()

MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20
CREATE_LIMIT = limit("replies.create", 60, 3600)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


async def _audit(db: DbTx, *, actor_id: int, action: str, reply: Reply) -> None:
    await crud_audit.log_action(
        db,
        actor_id=actor_id,
        action=action,
        target_type="reply",
        target_id=reply.id,
        metadata={
            "reply_id": reply.id,
            "thread_id": reply.thread_id,
            "parent_reply_id": reply.parent_reply_id,
        },
    )


@router.get(
    "/threads/{thread_id}/replies/",
    response_model=PaginatedReplies,
    responses=_error_responses(404, 422),
)
async def list_replies(
    thread_id: PathId,
    db: DbTx,
    user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginatedReplies:
    """Top-level replies on a thread the caller may see, oldest first, each with its replies
    (one level, oldest first). ``total`` counts top-level replies. A deleted reply that still
    has visible replies is kept as a placeholder (empty body, no author)."""
    thread = await crud_reply.get_visible_thread(db, thread_id=thread_id, user=user)
    total, replies = await crud_reply.list_replies(
        db, thread=thread, user=user, skip=skip, limit=limit_
    )
    return paginated_replies(total, replies)


@router.post(
    "/threads/{thread_id}/replies/",
    response_model=ReplyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(CREATE_LIMIT)],
    responses=_error_responses(401, 403, 404, 422, 423, 429),
)
async def create_reply(
    thread_id: PathId,
    body: ReplyCreate,
    user: VerifiedUser,
    db: DbTx,
    background_tasks: BackgroundTasks,
) -> ReplyOut:
    """Reply to a published, unlocked thread, or (``parent_reply_id``) to one of its top-level
    replies. Replies are published immediately. The thread and parent authors are emailed
    after the commit (background task; a failure there never fails this request)."""
    thread = await crud_reply.get_visible_thread(db, thread_id=thread_id, user=user)
    reply = await crud_reply.create_reply(
        db,
        thread=thread,
        author=user,
        body_html=body.body_html,
        parent_reply_id=body.parent_reply_id,
    )
    await _audit(db, actor_id=user.id, action="reply.created", reply=reply)
    background_tasks.add_task(notifications.send_reply_notifications, reply.id)
    return ReplyOut.model_validate(reply)


@router.patch(
    "/replies/{reply_id}",
    response_model=ReplyOut,
    responses=_error_responses(401, 403, 404, 422, 423),
)
async def update_reply(
    reply_id: BigPathId, body: ReplyUpdate, user: VerifiedUser, db: DbTx
) -> ReplyOut:
    """Edit a reply: its author within 24 hours of posting while the thread is unlocked, or an
    admin."""
    reply = await crud_reply.get_editable_reply(db, reply_id=reply_id, user=user)
    if await crud_reply.update_reply(db, reply=reply, user=user, body_html=body.body_html):
        await _audit(db, actor_id=user.id, action="reply.updated", reply=reply)
    refreshed = await crud_reply.get_reply(db, reply_id=reply.id)
    assert refreshed is not None
    return ReplyOut.model_validate(refreshed)


@router.delete(
    "/replies/{reply_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404),
)
async def delete_reply(reply_id: BigPathId, user: VerifiedUser, db: DbTx) -> Response:
    """Soft-delete a reply (its author, or an admin). Its replies stay in the thread."""
    reply = await crud_reply.get_editable_reply(db, reply_id=reply_id, user=user)
    await crud_reply.soft_delete_reply(db, reply=reply)
    await _audit(db, actor_id=user.id, action="reply.deleted", reply=reply)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
