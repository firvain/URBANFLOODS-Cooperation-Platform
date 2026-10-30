"""Members directory schemas: the public profile of a directory member.

Never exposes role, trust, login times or locale. ``email`` is set only when the member opted in
(``show_email``); the endpoint builds it with :func:`member_fields`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.api.v1.schemas.auth import OrganisationSummary
from app.api.v1.schemas.expertise import ExpertiseTagOut
from app.db.models import User

BIO_EXCERPT_LENGTH = 200
ELLIPSIS = "…"


def bio_excerpt(bio: str | None, length: int = BIO_EXCERPT_LENGTH) -> str | None:
    """The bio as one line (whitespace runs collapsed), cut to at most ``length`` characters
    with a trailing ellipsis when shortened."""
    if not bio:
        return None
    text = " ".join(bio.split())
    if len(text) <= length:
        return text
    return text[: length - len(ELLIPSIS)].rstrip() + ELLIPSIS


def member_fields(user: User) -> dict[str, Any]:
    """The public profile fields of ``user`` (``organisation`` and ``expertise`` loaded)."""
    return {
        "id": user.id,
        "display_name": user.display_name,
        "organisation": (
            OrganisationSummary.model_validate(user.organisation) if user.organisation else None
        ),
        "organisation_other": user.organisation_other,
        "country": user.country,
        "bio_excerpt": bio_excerpt(user.bio),
        "expertise": [ExpertiseTagOut.model_validate(tag) for tag in user.expertise],
        "email": user.email if user.show_email else None,
        "created_at": user.created_at,
    }


class MemberOut(BaseModel):
    id: int
    display_name: str
    organisation: OrganisationSummary | None
    organisation_other: str | None
    country: str | None
    bio_excerpt: str | None
    expertise: list[ExpertiseTagOut]
    # Only when the member chose to show it.
    email: str | None
    created_at: datetime


class MemberDetail(MemberOut):
    bio: str | None


class MemberList(BaseModel):
    total: int
    items: list[MemberOut]


class SuggestedMember(MemberOut):
    shared_expertise: int


class SuggestedMemberList(BaseModel):
    total: int
    items: list[SuggestedMember]
