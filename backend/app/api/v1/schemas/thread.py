"""Forum thread schemas: summaries for lists, details, create and partial update.

Shared building blocks (authors, categories, tags, KNOWBASE links, field types) come from
``schemas/post.py``. Reply schemas (increment 3c) can live here or in ``schemas/reply.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import Locale
from app.api.v1.schemas.post import (
    MAX_LINKS,
    MAX_TAGS,
    AuthorSummary,
    BodyHtml,
    CategorySummary,
    DbId,
    KnowbaseLinkIn,
    KnowbaseLinkOut,
    PostSlug,
    Title,
)
from app.api.v1.schemas.tag import TagOut
from app.db.enums import ContentStatus, HiddenReason
from app.services.sanitize import excerpt as make_excerpt

THREAD_EXCERPT_LENGTH = 200

ThreadSlug = PostSlug


# --- output -----------------------------------------------------------------------------------


class ThreadSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    # Threads store no excerpt: the start of ``body_text`` (at most 200 characters) is shown.
    excerpt: str = Field(validation_alias=AliasChoices("excerpt", "body_text"))
    locale: str
    status: ContentStatus
    category: CategorySummary
    author: AuthorSummary | None
    tags: list[TagOut]
    is_pinned: bool
    is_locked: bool
    reply_count: int
    last_activity_at: datetime
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("excerpt")
    @classmethod
    def _shorten(cls, value: str) -> str:
        return make_excerpt(value, THREAD_EXCERPT_LENGTH)


class ThreadDetail(ThreadSummary):
    body_html: str
    knowbase_links: list[KnowbaseLinkOut] = Field(default_factory=list)
    approved_at: datetime | None
    hidden_reason: HiddenReason | None
    deleted_at: datetime | None


class PaginatedThreads(BaseModel):
    total: int
    items: list[ThreadSummary]


def paginated_threads(total: int, threads: Iterable[Any]) -> PaginatedThreads:
    """A page of ORM threads (relations loaded) as summaries."""
    return PaginatedThreads(total=total, items=[ThreadSummary.model_validate(t) for t in threads])


# --- input ------------------------------------------------------------------------------------


class ThreadCreate(BaseModel):
    title: Title
    body_html: BodyHtml
    category_id: DbId
    locale: Locale = "en"
    tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = Field(default_factory=list)
    knowbase_links: Annotated[list[KnowbaseLinkIn], Field(max_length=MAX_LINKS)] = Field(
        default_factory=list
    )


class ThreadUpdate(BaseModel):
    """Partial update: only fields present in the body are applied; none may be ``null``.
    ``slug`` is for admins only."""

    title: Title | None = None
    body_html: BodyHtml | None = None
    category_id: DbId | None = None
    locale: Locale | None = None
    tags: Annotated[list[str], Field(max_length=MAX_TAGS)] | None = None
    knowbase_links: Annotated[list[KnowbaseLinkIn], Field(max_length=MAX_LINKS)] | None = None
    slug: ThreadSlug | None = None

    @field_validator(
        "title", "body_html", "category_id", "locale", "tags", "knowbase_links", "slug"
    )
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value
