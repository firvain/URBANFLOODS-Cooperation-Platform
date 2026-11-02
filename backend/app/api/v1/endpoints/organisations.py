"""Organisations: public list and detail (the ``/partners`` page), admin create and update."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.v1.params import PathId
from app.api.v1.schemas.organisation import (
    OrganisationCreate,
    OrganisationList,
    OrganisationOut,
    OrganisationUpdate,
)
from app.core.deps import AdminUser, DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import organisation as crud_organisation
from app.db.models import Organisation

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


def _out(organisation: Organisation, member_count: int) -> OrganisationOut:
    return OrganisationOut.model_validate(organisation).model_copy(
        update={"member_count": member_count}
    )


def _not_found() -> AppError:
    return AppError(404, "organisations.not_found", "Organisation not found.")


@router.get("/", response_model=OrganisationList, responses=_error_responses(422))
async def list_organisations(
    db: DbTx,
    partners_only: bool | None = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> OrganisationList:
    """All organisations, project partners first (LP/PP, then AP, by ``sort_order``)."""
    total, rows = await crud_organisation.list_organisations(
        db, partners_only=partners_only, q=q, skip=skip, limit=limit
    )
    return OrganisationList(total=total, items=[_out(org, count) for org, count in rows])


@router.get(
    "/{organisation_id}", response_model=OrganisationOut, responses=_error_responses(404, 422)
)
async def get_organisation(organisation_id: PathId, db: DbTx) -> OrganisationOut:
    """One organisation with its number of (verified, active) members."""
    row = await crud_organisation.get_organisation_with_member_count(
        db, organisation_id=organisation_id
    )
    if row is None:
        raise _not_found()
    return _out(*row)


@router.post(
    "/",
    response_model=OrganisationOut,
    status_code=status.HTTP_201_CREATED,
    responses=_error_responses(401, 403, 409, 422),
)
async def create_organisation(
    body: OrganisationCreate, admin: AdminUser, db: DbTx
) -> OrganisationOut:
    """Add an organisation (admin)."""
    organisation = await crud_organisation.create_organisation(db, **body.model_dump())
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="organisation.created",
        target_type="organisation",
        target_id=organisation.id,
        metadata={"name": organisation.name},
    )
    return _out(organisation, 0)


@router.patch(
    "/{organisation_id}",
    response_model=OrganisationOut,
    responses=_error_responses(401, 403, 404, 409, 422),
)
async def update_organisation(
    organisation_id: PathId, body: OrganisationUpdate, admin: AdminUser, db: DbTx
) -> OrganisationOut:
    """Update an organisation (admin). Omitted fields are kept; ``website: null`` clears."""
    organisation = await crud_organisation.get_organisation(db, organisation_id=organisation_id)
    if organisation is None:
        raise _not_found()
    changed = await crud_organisation.update_organisation(
        db, organisation=organisation, changes=body.model_dump(exclude_unset=True)
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=admin.id,
            action="organisation.updated",
            target_type="organisation",
            target_id=organisation.id,
            metadata={"fields": changed},
        )
    row = await crud_organisation.get_organisation_with_member_count(
        db, organisation_id=organisation_id
    )
    assert row is not None
    return _out(*row)
