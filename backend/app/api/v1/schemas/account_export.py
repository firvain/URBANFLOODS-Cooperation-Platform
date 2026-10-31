"""``GET /auth/me/export``: everything stored about the signed-in member (GDPR art. 15/20).

The member's own content is exported in every status (pending, published, hidden, deleted):
it is their data. Nothing here names another member or an admin: no ``approved_by``, no
``resolved_by``, no hashes; uploads are given as public URLs, not raw storage paths. Names
start with ``Exported`` so they never clash with the public FAIR export schemas
(``schemas/export.py``) in the OpenAPI document.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.api.v1.schemas.auth import (
    ExportAuditEntry,
    ExportSession,
    ExportUser,
    NotificationPreferences,
)
from app.api.v1.schemas.post import CategorySummary, KnowbaseLinkOut
from app.api.v1.schemas.tag import TagOut
from app.api.v1.schemas.upload import upload_url
from app.db.enums import ContentStatus, ContentType, HiddenReason, ReportReason, ReportStatus

FORMAT_VERSION = 2


class _ExportedBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body_html: str
    body_text: str
    status: ContentStatus
    hidden_reason: HiddenReason | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class _ExportedTopic(_ExportedBody):
    """Fields shared by posts and threads."""

    slug: str
    title: str
    locale: str
    category: CategorySummary
    tags: list[TagOut]
    published_at: datetime | None
    knowbase_links: list[KnowbaseLinkOut] = Field(default_factory=list)


class ExportedPost(_ExportedTopic):
    excerpt: str | None
    cover_attachment_id: int | None
    event_at: datetime | None
    event_url: str | None


class ExportedThread(_ExportedTopic):
    is_pinned: bool
    is_locked: bool


class ExportedReply(_ExportedBody):
    thread_id: int
    parent_reply_id: int | None


class ExportedComment(_ExportedBody):
    post_id: int


class ExportedAttachment(BaseModel):
    """An upload of the member's (deleted ones included until they are purged)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_path: str = Field(exclude=True)
    thumb_path: str | None = Field(default=None, exclude=True)
    original_filename: str
    mime: str
    size_bytes: int
    width: int
    height: int
    alt_text: str
    created_at: datetime
    deleted_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return upload_url(self.storage_path) or ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def thumb_url(self) -> str | None:
        return upload_url(self.thumb_path)


class ExportedReport(BaseModel):
    """A report the member made (never who resolved it)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: ContentType
    content_id: int
    reason: ReportReason
    details: str | None
    status: ReportStatus
    created_at: datetime
    resolved_at: datetime | None


class ExportContent(BaseModel):
    """The member's own content, every status, oldest first."""

    posts: list[ExportedPost] = Field(default_factory=list)
    threads: list[ExportedThread] = Field(default_factory=list)
    replies: list[ExportedReply] = Field(default_factory=list)
    comments: list[ExportedComment] = Field(default_factory=list)


class AccountExport(BaseModel):
    """``GET /me/export``: everything stored about the signed-in user (GDPR art. 15/20)."""

    exported_at: datetime
    format_version: int
    licence_note: str
    user: ExportUser
    notification_preferences: NotificationPreferences | None
    sessions: list[ExportSession]
    audit_log: list[ExportAuditEntry]
    content: ExportContent
    attachments: list[ExportedAttachment]
    reports_made: list[ExportedReport]
