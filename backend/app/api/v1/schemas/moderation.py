"""Admin moderation schemas: the pending queue, the deleted items, action bodies/results and the
audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.db.enums import ContentStatus, ContentType, HiddenReason
from app.services.sanitize import plain_text

REASON_MAX_LENGTH = 500
EXCERPT_LENGTH = 200

Reason = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=REASON_MAX_LENGTH),
    # Plain text: control characters (a NUL would break the audit row) dropped; blank: none.
    AfterValidator(lambda value: plain_text(value, REASON_MAX_LENGTH)),
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
    # Rejected once and sent for approval again by its author (it still has the admin's note).
    resubmitted: bool


class ModerationQueue(BaseModel):
    total: int
    items: list[QueueItem]


# --- deleted items ----------------------------------------------------------------------------


class DeletedUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class DeletedItem(BaseModel):
    content_type: ContentType
    id: int
    title: str
    slug: str
    author: DeletedUser | None
    category: QueueCategory
    deleted_at: datetime
    # The actor of the latest deletion's audit row (the author or an admin); null when unknown.
    deleted_by: DeletedUser | None
    # When the maintenance sweep removes it for good (``deleted_at`` plus
    # ``DELETED_CONTENT_RETENTION_DAYS``); null when automatic removal is off.
    purge_at: datetime | None


class DeletedPage(BaseModel):
    total: int
    items: list[DeletedItem]


# --- actions ----------------------------------------------------------------------------------


class ModerationReason(BaseModel):
    """Optional body of ``reject`` and ``hide``. The reason goes into the audit row; a rejection's
    reason is also stored on the item as its ``moderation_note``, which the author sees."""

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
    # The page of a post/thread target that still exists (any status): ``/blog/<slug>`` or
    # ``/forum/t/<slug>``; null otherwise.
    target_path: str | None = None


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogEntry]
