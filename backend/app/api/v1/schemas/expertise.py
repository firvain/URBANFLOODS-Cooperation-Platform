"""Expertise vocabulary schemas (public list; admin create/update)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

LABEL_MIN_LENGTH = 2
LABEL_MAX_LENGTH = 80
# The column is String(64).
SLUG_MAX_LENGTH = 64
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

ExpertiseLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=LABEL_MIN_LENGTH, max_length=LABEL_MAX_LENGTH
    ),
]
ExpertiseSlug = Annotated[str, StringConstraints(max_length=SLUG_MAX_LENGTH, pattern=SLUG_PATTERN)]
SortOrder = Annotated[int, Field(ge=0, le=100_000)]


class ExpertiseTagOut(BaseModel):
    """One expertise area. ``label`` is English; the frontend translates by ``slug``. A
    deactivated tag (``is_active: false``) stays on the members who hold it but cannot be picked
    any more."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    label: str
    sort_order: int
    is_active: bool


class ExpertiseTagList(BaseModel):
    total: int
    items: list[ExpertiseTagOut]


class ExpertiseTagCreate(BaseModel):
    label: ExpertiseLabel
    # Derived from ``label`` when omitted.
    slug: ExpertiseSlug | None = None
    sort_order: SortOrder = 0


class ExpertiseTagUpdate(BaseModel):
    """Partial update: only fields present in the body are applied; none may be ``null``."""

    label: ExpertiseLabel | None = None
    slug: ExpertiseSlug | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None

    @field_validator("label", "slug", "sort_order", "is_active")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value
