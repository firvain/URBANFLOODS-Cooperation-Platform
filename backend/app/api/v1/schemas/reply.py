"""Forum reply schemas: output (top-level replies carry their children), page, create and
update."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from app.api.v1.params import BigDbId
from app.api.v1.schemas.comment import EDIT_GRACE
from app.api.v1.schemas.post import AuthorSummary
from app.db.enums import ContentStatus

# Raw HTML bound; the 10 000-character limit applies to the sanitised text (crud/reply.py).
BODY_HTML_MAX_LENGTH = 100_000

ReplyBodyHtml = Annotated[str, StringConstraints(max_length=BODY_HTML_MAX_LENGTH)]


class ReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int
    parent_reply_id: int | None
    author: AuthorSummary | None
    body_html: str
    status: ContentStatus
    created_at: datetime
    updated_at: datetime
    # Only top-level replies from ``crud.reply.list_replies`` have children.
    children: list[ReplyOut] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: Any) -> Any:
        """Read an ORM reply. Children come from the plain ``visible_children`` attribute set by
        ``crud.reply.list_replies`` (never the lazy ``children`` relationship); a reply marked
        ``is_placeholder`` keeps its id, place and status but loses its body and author."""
        if isinstance(data, dict | BaseModel):
            return data
        placeholder = getattr(data, "is_placeholder", False)
        return {
            "id": data.id,
            "thread_id": data.thread_id,
            "parent_reply_id": data.parent_reply_id,
            "author": None if placeholder else data.author,
            "body_html": "" if placeholder else data.body_html,
            "status": data.status,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "children": list(getattr(data, "visible_children", ())),
        }

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_edited(self) -> bool:
        return self.updated_at > self.created_at + EDIT_GRACE


class PaginatedReplies(BaseModel):
    # Top-level replies only.
    total: int
    items: list[ReplyOut]


def paginated_replies(total: int, replies: Iterable[Any]) -> PaginatedReplies:
    """A page of top-level ORM replies from ``crud.reply.list_replies``."""
    return PaginatedReplies(total=total, items=[ReplyOut.model_validate(r) for r in replies])


class ReplyCreate(BaseModel):
    body_html: ReplyBodyHtml
    parent_reply_id: BigDbId | None = None


class ReplyUpdate(BaseModel):
    body_html: ReplyBodyHtml
