"""Blog post comment schemas: output, page, create and update."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, computed_field

from app.api.v1.schemas.post import AuthorSummary
from app.db.enums import ContentStatus

# Raw HTML bound; the 5000-character limit applies to the sanitised text (crud/comment.py).
BODY_HTML_MAX_LENGTH = 50_000
# Saves within this long of creation do not count as edits.
EDIT_GRACE = timedelta(seconds=5)

CommentBodyHtml = Annotated[str, StringConstraints(max_length=BODY_HTML_MAX_LENGTH)]


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    author: AuthorSummary | None
    body_html: str
    status: ContentStatus
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_edited(self) -> bool:
        return self.updated_at > self.created_at + EDIT_GRACE


class PaginatedComments(BaseModel):
    total: int
    items: list[CommentOut]


def paginated_comments(total: int, comments: Iterable[Any]) -> PaginatedComments:
    """A page of ORM comments (authors loaded)."""
    return PaginatedComments(total=total, items=[CommentOut.model_validate(c) for c in comments])


class CommentCreate(BaseModel):
    body_html: CommentBodyHtml


class CommentUpdate(BaseModel):
    body_html: CommentBodyHtml
