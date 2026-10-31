"""Tags: public list (search, popular/name sort), admin delete and merge."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.v1.schemas.tag import TagList, TagMerge, TagOut
from app.core.deps import AdminUser, DbTx
from app.core.exceptions import error_body
from app.crud import audit as crud_audit
from app.crud import tag as crud_tag
from app.crud.tag import TagSort

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@router.get("/", response_model=TagList, responses=_error_responses(422))
async def list_tags(
    db: DbTx,
    q: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    sort: TagSort = "popular",
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TagList:
    """Tags, most used first (or by name); ``q`` matches part of the name."""
    total, tags = await crud_tag.list_tags(db, q=q, sort=sort, skip=skip, limit=limit)
    return TagList(total=total, items=[TagOut.model_validate(tag) for tag in tags])


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404),
)
async def delete_tag(tag_id: int, admin: AdminUser, db: DbTx) -> Response:
    """Delete a tag (admin); it is removed from every post."""
    tag = await crud_tag.get_tag(db, tag_id=tag_id)
    if tag is None:
        raise crud_tag.not_found()
    metadata = {"slug": tag.slug, "name": tag.name}
    await crud_tag.delete_tag(db, tag=tag)
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="tag.deleted",
        target_type="tag",
        target_id=tag_id,
        metadata=metadata,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tag_id}/merge", response_model=TagOut, responses=_error_responses(401, 403, 404, 409, 422)
)
async def merge_tag(tag_id: int, body: TagMerge, admin: AdminUser, db: DbTx) -> TagOut:
    """Merge this tag into ``target_id`` (admin): its posts move to the target, it is deleted."""
    target = await crud_tag.merge_tags(db, source_id=tag_id, target_id=body.target_id)
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="tag.merged",
        target_type="tag",
        target_id=target.id,
        metadata={"source_id": tag_id, "target_id": target.id},
    )
    return TagOut.model_validate(target)
