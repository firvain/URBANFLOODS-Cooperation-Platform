"""Organisation schemas (public list/detail feeding ``/partners``; admin create/update)."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import Country
from app.db.enums import OrganisationType

WEBSITE_MAX_LENGTH = 500


def check_website(value: str | None) -> str | None:
    """An absolute ``http(s)`` URL with a host, or None (blank becomes None)."""
    if value is None or value == "":
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        parts = None
    if (
        parts is None
        or parts.scheme.lower() not in {"http", "https"}
        or not parts.hostname
        or any(char.isspace() for char in value)
    ):
        raise PydanticCustomError("invalid_url", "Use an http:// or https:// address")
    return value


OrganisationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
]
ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Website = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=WEBSITE_MAX_LENGTH),
    AfterValidator(check_website),
]
SortOrder = Annotated[int, Field(ge=0, le=100_000)]


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str
    country: str
    type: OrganisationType
    website: str | None
    is_partner: bool
    sort_order: int
    member_count: int = 0


class OrganisationList(BaseModel):
    total: int
    items: list[OrganisationOut]


class OrganisationCreate(BaseModel):
    name: OrganisationName
    short_name: ShortName
    country: Country
    type: OrganisationType
    website: Website = None
    is_partner: bool = False
    sort_order: SortOrder = 0

    @field_validator("country")
    @classmethod
    def _country_required(cls, value: str | None) -> str:
        if value is None:
            raise PydanticCustomError("missing", "A country is required")
        return value


class OrganisationUpdate(BaseModel):
    """Partial update: only fields present in the body are applied. Only ``website`` may be
    cleared with ``null``."""

    name: OrganisationName | None = None
    short_name: ShortName | None = None
    country: Country = None
    type: OrganisationType | None = None
    website: Website = None
    is_partner: bool | None = None
    sort_order: SortOrder | None = None

    @field_validator("name", "short_name", "country", "type", "is_partner", "sort_order")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value
