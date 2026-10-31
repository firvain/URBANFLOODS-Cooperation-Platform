"""Members directory (Collaboration Network): list and profile of members who chose to be listed,
and suggested collaborators for the signed-in member (partner matchmaking). All three routes need
a verified account (401 signed out, 403 unverified); the directory is not public."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.v1.schemas.auth import Country
from app.api.v1.schemas.member import (
    MemberDetail,
    MemberList,
    MemberOut,
    SuggestedMember,
    SuggestedMemberList,
    member_fields,
)
from app.core.deps import DbTx, VerifiedUser
from app.core.exceptions import AppError, error_body
from app.crud import member as crud_member

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@router.get("/", response_model=MemberList, responses=_error_responses(401, 403, 422))
async def list_members(
    _user: VerifiedUser,
    db: DbTx,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    expertise_ids: Annotated[list[int] | None, Query()] = None,
    country: Annotated[Country, Query()] = None,
    organisation_id: int | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> MemberList:
    """Directory members, newest first. ``expertise_ids`` (repeatable) matches any of the
    tags; ``q`` searches names and organisations."""
    total, users = await crud_member.list_members(
        db,
        q=q,
        expertise_ids=expertise_ids,
        country=country,
        organisation_id=organisation_id,
        skip=skip,
        limit=limit,
    )
    return MemberList(total=total, items=[MemberOut(**member_fields(user)) for user in users])


@router.get("/suggested", response_model=SuggestedMemberList, responses=_error_responses(401, 403))
async def suggested_members(user: VerifiedUser, db: DbTx) -> SuggestedMemberList:
    """Up to six members sharing the most expertise with the signed-in member, topped up with
    the newest members."""
    rows = await crud_member.suggested_members(db, user=user)
    items = [
        SuggestedMember(**member_fields(member), shared_expertise=count) for member, count in rows
    ]
    return SuggestedMemberList(total=len(items), items=items)


@router.get(
    "/{member_id}", response_model=MemberDetail, responses=_error_responses(401, 403, 404, 422)
)
async def get_member(member_id: int, _user: VerifiedUser, db: DbTx) -> MemberDetail:
    """One directory member's profile."""
    user = await crud_member.get_member(db, user_id=member_id)
    if user is None:
        raise AppError(404, "members.not_found", "Member not found.")
    return MemberDetail(**member_fields(user), bio=user.bio)
