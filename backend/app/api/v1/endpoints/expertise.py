"""Expertise vocabulary: the public list of active tags (profile editor, directory filter) and
admin create and update (deactivate instead of delete)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.api.v1.schemas.expertise import (
    ExpertiseTagCreate,
    ExpertiseTagList,
    ExpertiseTagOut,
    ExpertiseTagUpdate,
)
from app.core.deps import ADMIN_ROLES, AdminUser, CurrentUser, DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import expertise as crud_expertise

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@router.get("/", response_model=ExpertiseTagList, responses=_error_responses(422))
async def list_expertise(
    db: DbTx, user: CurrentUser, include_inactive: bool = False
) -> ExpertiseTagList:
    """Expertise tags in display order. ``include_inactive`` is honoured for admins only;
    everyone else always gets the active tags."""
    is_admin = user is not None and user.is_verified and user.role in ADMIN_ROLES
    tags = await crud_expertise.list_tags(db, include_inactive=include_inactive and is_admin)
    return ExpertiseTagList(
        total=len(tags), items=[ExpertiseTagOut.model_validate(tag) for tag in tags]
    )


@router.post(
    "/",
    response_model=ExpertiseTagOut,
    status_code=status.HTTP_201_CREATED,
    responses=_error_responses(401, 403, 409, 422),
)
async def create_expertise(body: ExpertiseTagCreate, admin: AdminUser, db: DbTx) -> ExpertiseTagOut:
    """Add an expertise tag (admin). The slug is derived from the label when omitted."""
    tag = await crud_expertise.create_tag(db, **body.model_dump())
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="expertise.created",
        target_type="expertise_tag",
        target_id=tag.id,
        metadata={"slug": tag.slug, "label": tag.label},
    )
    return ExpertiseTagOut.model_validate(tag)


@router.patch(
    "/{tag_id}",
    response_model=ExpertiseTagOut,
    responses=_error_responses(401, 403, 404, 409, 422),
)
async def update_expertise(
    tag_id: int, body: ExpertiseTagUpdate, admin: AdminUser, db: DbTx
) -> ExpertiseTagOut:
    """Update an expertise tag (admin). Omitted fields are kept. ``is_active: false``
    deactivates: members keep the tag, nobody can pick it any more."""
    tag = await crud_expertise.get_tag(db, tag_id=tag_id)
    if tag is None:
        raise AppError(404, "expertise.not_found", "Expertise tag not found.")
    changed = await crud_expertise.update_tag(
        db, tag=tag, changes=body.model_dump(exclude_unset=True)
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=admin.id,
            action="expertise.updated",
            target_type="expertise_tag",
            target_id=tag.id,
            metadata={"fields": changed},
        )
    return ExpertiseTagOut.model_validate(tag)
