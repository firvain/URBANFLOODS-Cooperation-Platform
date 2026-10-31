"""Blog post schemas: summaries for lists, details, create and partial update."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AliasPath,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_serializer,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import Locale, OrganisationSummary
from app.api.v1.schemas.tag import TagOut
from app.api.v1.schemas.upload import upload_url
from app.db.enums import CategoryKind, ContentStatus, HiddenReason, KbType
from app.services.sanitize import validate_external_url

TITLE_MIN_LENGTH = 3
TITLE_MAX_LENGTH = 200
EXCERPT_MAX_LENGTH = 500
BODY_MAX_LENGTH = 200_000
SLUG_MAX_LENGTH = 220
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
MAX_TAGS = 10
MAX_LINKS = 10
MAX_ID = 2**31 - 1

KNOWBASE_FRONTEND_PATHS = {KbType.DOCUMENT: "documents", KbType.MEASURE: "measures"}


def _external_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_external_url(value)
    except ValueError as exc:
        raise PydanticCustomError("invalid", "Not an acceptable http(s) URL") from exc


Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH
    ),
]
BodyHtml = Annotated[str, StringConstraints(max_length=BODY_MAX_LENGTH)]
Excerpt = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=EXCERPT_MAX_LENGTH),
    AfterValidator(lambda value: value or None),  # blank: generated from the body
]
EventUrl = Annotated[str | None, AfterValidator(_external_url)]
PostSlug = Annotated[str, StringConstraints(max_length=SLUG_MAX_LENGTH, pattern=SLUG_PATTERN)]
DbId = Annotated[int, Field(ge=1, le=MAX_ID)]


# --- output -----------------------------------------------------------------------------------


class AuthorSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    organisation: OrganisationSummary | None
    # Read from ``user.avatar.storage_path`` (eagerly loaded); served as the public URL.
    avatar_url: str | None = Field(
        default=None, validation_alias=AliasPath("avatar", "storage_path")
    )
    # Read from the ``User`` row only to work out ``has_profile``; never serialised.
    is_verified: bool = Field(exclude=True)
    is_active: bool = Field(exclude=True)
    deleted_at: datetime | None = Field(exclude=True)
    show_in_directory: bool = Field(exclude=True)

    @field_serializer("avatar_url")
    def _avatar_url(self, storage_path: str | None) -> str | None:
        return upload_url(storage_path)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_profile(self) -> bool:
        """Whether ``/u/{id}`` exists for other members: the same rule as the member
        directory (``crud/member.py::_in_directory``), so a link never leads to a 404."""
        return (
            self.is_verified
            and self.is_active
            and self.deleted_at is None
            and self.show_in_directory
        )


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CategoryKind
    slug: str
    name: str


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_path: str = Field(exclude=True)
    thumb_path: str | None = Field(default=None, exclude=True)
    width: int
    height: int
    alt_text: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return upload_url(self.storage_path) or ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def thumb_url(self) -> str | None:
        return upload_url(self.thumb_path)


class KnowbaseLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kb_type: KbType
    kb_id: int
    title_en: str = Field(validation_alias="cached_title_en")
    title_local: str | None = Field(default=None, validation_alias="cached_title_local")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        """The item's page on this platform's frontend."""
        return f"/knowbase/{KNOWBASE_FRONTEND_PATHS[self.kb_type]}/{self.kb_id}"


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    excerpt: str | None
    locale: str
    status: ContentStatus
    category: CategorySummary
    author: AuthorSummary | None
    cover: AttachmentOut | None
    tags: list[TagOut]
    event_at: datetime | None
    event_url: str | None
    comment_count: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PostDetail(PostSummary):
    body_html: str
    knowbase_links: list[KnowbaseLinkOut] = Field(default_factory=list)
    approved_at: datetime | None
    hidden_reason: HiddenReason | None
    # The admin's note on the last rejection. Only the author and admins ever get a detail of
    # hidden or pending content, and approval clears the note, so it never reaches the public.
    moderation_note: str | None
    deleted_at: datetime | None


class PaginatedPosts(BaseModel):
    total: int
    items: list[PostSummary]


def paginated_posts(total: int, posts: Iterable[Any]) -> PaginatedPosts:
    """A page of ORM posts (relations loaded) as summaries."""
    return PaginatedPosts(total=total, items=[PostSummary.model_validate(p) for p in posts])


# --- input ------------------------------------------------------------------------------------


class KnowbaseLinkIn(BaseModel):
    kb_type: KbType
    kb_id: DbId


class PostCreate(BaseModel):
    title: Title
    body_html: BodyHtml
    category_id: DbId
    excerpt: Excerpt = None
    cover_attachment_id: DbId | None = None
    locale: Locale = "en"
    event_at: AwareDatetime | None = None
    event_url: EventUrl = None
    tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = Field(default_factory=list)
    knowbase_links: Annotated[list[KnowbaseLinkIn], Field(max_length=MAX_LINKS)] = Field(
        default_factory=list
    )


class PostUpdate(BaseModel):
    """Partial update: only fields present in the body are applied. ``excerpt``,
    ``cover_attachment_id``, ``event_at`` and ``event_url`` may be cleared with ``null`` (a
    cleared excerpt is generated from the body); ``slug`` is for admins only."""

    title: Title | None = None
    body_html: BodyHtml | None = None
    category_id: DbId | None = None
    excerpt: Excerpt = None
    cover_attachment_id: DbId | None = None
    locale: Locale | None = None
    event_at: AwareDatetime | None = None
    event_url: EventUrl = None
    tags: Annotated[list[str], Field(max_length=MAX_TAGS)] | None = None
    knowbase_links: Annotated[list[KnowbaseLinkIn], Field(max_length=MAX_LINKS)] | None = None
    slug: PostSlug | None = None

    @field_validator(
        "title", "body_html", "category_id", "locale", "tags", "knowbase_links", "slug"
    )
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value
