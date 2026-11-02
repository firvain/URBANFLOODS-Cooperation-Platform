"""Comments on blog posts: public list (when the post is visible), create (verified, rate
limited), edit (author within 24 h, or an admin) and soft delete (author or admin).

Mounted at the API root: ``/posts/{post_id}/comments/`` and ``/comments/{comment_id}``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.api.v1.params import BigPathId, PathId
from app.api.v1.schemas.comment import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
    PaginatedComments,
    paginated_comments,
)
from app.core.deps import CurrentUser, DbTx, VerifiedUser
from app.core.exceptions import error_body
from app.core.rate_limit import limit
from app.crud import audit as crud_audit
from app.crud import comment as crud_comment
from app.db.models import Comment
from app.services import notifications

router = APIRouter()

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
CREATE_LIMIT = limit("comments.create", 30, 3600)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


async def _audit(db: DbTx, *, actor_id: int, action: str, comment: Comment) -> None:
    await crud_audit.log_action(
        db,
        actor_id=actor_id,
        action=action,
        target_type="comment",
        target_id=comment.id,
        metadata={"comment_id": comment.id, "post_id": comment.post_id},
    )


@router.get(
    "/posts/{post_id}/comments/",
    response_model=PaginatedComments,
    responses=_error_responses(404, 422),
)
async def list_comments(
    post_id: PathId,
    db: DbTx,
    user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginatedComments:
    """Comments on a post the caller may see, oldest first. Deleted comments are left out."""
    post = await crud_comment.get_visible_post(db, post_id=post_id, user=user)
    total, comments = await crud_comment.list_comments(
        db, post=post, user=user, skip=skip, limit=limit_
    )
    return paginated_comments(total, comments)


@router.post(
    "/posts/{post_id}/comments/",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(CREATE_LIMIT)],
    responses=_error_responses(401, 403, 404, 422, 429),
)
async def create_comment(
    post_id: PathId,
    body: CommentCreate,
    user: VerifiedUser,
    db: DbTx,
    background_tasks: BackgroundTasks,
) -> CommentOut:
    """Comment on a published post. Comments are published immediately. The post author is
    emailed after the commit (background task; a failure there never fails this request)."""
    post = await crud_comment.get_visible_post(db, post_id=post_id, user=user)
    comment = await crud_comment.create_comment(
        db, post=post, author=user, body_html=body.body_html
    )
    await _audit(db, actor_id=user.id, action="comment.created", comment=comment)
    background_tasks.add_task(notifications.send_comment_notifications, comment.id)
    return CommentOut.model_validate(comment)


@router.patch(
    "/comments/{comment_id}",
    response_model=CommentOut,
    responses=_error_responses(401, 403, 404, 422),
)
async def update_comment(
    comment_id: BigPathId, body: CommentUpdate, user: VerifiedUser, db: DbTx
) -> CommentOut:
    """Edit a comment: its author within 24 hours of posting, or an admin."""
    comment = await crud_comment.get_editable_comment(db, comment_id=comment_id, user=user)
    if await crud_comment.update_comment(db, comment=comment, user=user, body_html=body.body_html):
        await _audit(db, actor_id=user.id, action="comment.updated", comment=comment)
    refreshed = await crud_comment.get_comment(db, comment_id=comment.id)
    assert refreshed is not None
    return CommentOut.model_validate(refreshed)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404),
)
async def delete_comment(comment_id: BigPathId, user: VerifiedUser, db: DbTx) -> Response:
    """Soft-delete a comment (its author, or an admin)."""
    comment = await crud_comment.get_editable_comment(db, comment_id=comment_id, user=user)
    await crud_comment.soft_delete_comment(db, comment=comment)
    await _audit(db, actor_id=user.id, action="comment.deleted", comment=comment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
