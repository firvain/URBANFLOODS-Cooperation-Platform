"""Admin moderation schemas: the pending queue, action bodies/results and the audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.db.enums import ContentStatus, ContentType, HiddenReason

REASON_MAX_LENGTH = 500
EXCERPT_LENGTH = 200

Reason = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=REASON_MAX_LENGTH),
    AfterValidator(lambda value: value or None),  # blank: no reason
]


# --- queue ------------------------------------------------------------------------------------


class QueueAuthor(BaseModel):
    id: int
    display_name: str
    trusted: bool


class QueueCategory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class QueueItem(BaseModel):
    content_type: ContentType
    id: int
    title: str
    slug: str
    excerpt: str
    locale: str
    author: QueueAuthor | None
    category: QueueCategory
    created_at: datetime


class ModerationQueue(BaseModel):
    total: int
    items: list[QueueItem]


# --- actions ----------------------------------------------------------------------------------


class ModerationReason(BaseModel):
    """Optional body of ``reject`` and ``hide``; the reason goes into the audit row only."""

    reason: Reason = None


class ModerationResult(BaseModel):
    content_type: ContentType
    id: int
    status: ContentStatus
    hidden_reason: HiddenReason | None
    # Replies and comments have no ``published_at``: always null for them.
    published_at: datetime | None
    deleted_at: datetime | None
    author_trusted: bool


class PurgeResultOut(BaseModel):
    """Response of ``purge``: the item is gone; counts of what went with it."""

    model_config = ConfigDict(from_attributes=True)

    content_type: ContentType
    id: int
    purged: Literal[True] = True
    children_deleted: int
    attachments_deleted: int
    reports_resolved: int


# --- log --------------------------------------------------------------------------------------


class LogActor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    actor: LogActor | None
    target_type: str | None
    target_id: int | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogEntry]
