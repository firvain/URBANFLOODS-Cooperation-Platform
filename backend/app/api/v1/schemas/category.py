"""Category schemas (public list/detail; admin create/update)."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import Locale
from app.db.enums import CategoryKind

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 80
SLUG_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 500
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

CategoryName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH
    ),
]
TranslatedName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
# Keys are limited to the 9 interface locales.
NameI18n = dict[Locale, TranslatedName]
CategorySlug = Annotated[str, StringConstraints(max_length=SLUG_MAX_LENGTH, pattern=SLUG_PATTERN)]
Description = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=DESCRIPTION_MAX_LENGTH),
    AfterValidator(lambda value: value or None),  # blank becomes None
]
SortOrder = Annotated[int, Field(ge=0, le=100_000)]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CategoryKind
    slug: str
    name: str
    name_i18n: dict[str, str]
    description: str | None
    sort_order: int
    is_archived: bool
    admin_only: bool
    post_count: int = 0


class CategoryList(BaseModel):
    total: int
    items: list[CategoryOut]


class CategoryCreate(BaseModel):
    kind: CategoryKind
    name: CategoryName
    # Derived from ``name`` when omitted.
    slug: CategorySlug | None = None
    name_i18n: NameI18n = Field(default_factory=dict)
    description: Description = None
    sort_order: SortOrder = 0
    admin_only: bool = False


class CategoryUpdate(BaseModel):
    """Partial update: only fields present in the body are applied. Only ``description`` may be
    cleared with ``null``. ``slug`` can change only while the category has no posts."""

    name: CategoryName | None = None
    slug: CategorySlug | None = None
    name_i18n: NameI18n | None = None
    description: Description = None
    sort_order: SortOrder | None = None
    admin_only: bool | None = None
    is_archived: bool | None = None

    @field_validator("name", "slug", "name_i18n", "sort_order", "admin_only", "is_archived")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value
