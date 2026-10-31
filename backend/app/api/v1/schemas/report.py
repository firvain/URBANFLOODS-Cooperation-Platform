"""Report schemas: create (member), the creation result, and the admin detail/page with a
summary of the reported content."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.db.enums import ContentStatus, ContentType, ReportReason, ReportStatus
from app.db.models import Comment, Post, Reply, Report, Thread
from app.services.sanitize import excerpt

DETAILS_MAX_LENGTH = 1000
CONTENT_EXCERPT_LENGTH = 160
MAX_CONTENT_ID = 2**63 - 1


def _blank_to_none(value: str | None) -> str | None:
    return value or None


# Stripped first, then length-checked; an empty result is stored as NULL.
Details = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=DETAILS_MAX_LENGTH),
    AfterValidator(_blank_to_none),
]


class ReportCreate(BaseModel):
    content_type: ContentType
    content_id: int = Field(ge=1, le=MAX_CONTENT_ID)
    reason: ReportReason
    details: Details = None


class ReportCreated(BaseModel):
    """What the reporter gets back (no details, nothing about other reports)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: ContentType
    content_id: int
    reason: ReportReason
    status: ReportStatus
    created_at: datetime
    auto_hidden: bool


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class ContentSummary(BaseModel):
    """The reported item, whatever its status. ``url_slug`` is the post/thread slug; replies and
    comments carry their thread's / post's slug so the admin UI can link to them."""

    type: ContentType
    id: int
    title: str | None = None
    excerpt: str
    status: ContentStatus
    author_id: int | None
    url_slug: str | None = None


def content_summary(content: Post | Thread | Reply | Comment) -> ContentSummary:
    """The summary of a loaded content row (a reply's thread / a comment's post loaded)."""
    title: str | None = None
    if isinstance(content, Post | Thread):
        content_type = ContentType.POST if isinstance(content, Post) else ContentType.THREAD
        title, slug = content.title, content.slug
    elif isinstance(content, Reply):
        content_type, slug = ContentType.REPLY, content.thread.slug
    else:
        content_type, slug = ContentType.COMMENT, content.post.slug
    return ContentSummary(
        type=content_type,
        id=content.id,
        title=title,
        excerpt=excerpt(content.body_text or "", CONTENT_EXCERPT_LENGTH),
        status=content.status,
        author_id=content.author_id,
        url_slug=slug,
    )


class ReportDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: ContentType
    content_id: int
    reason: ReportReason
    details: str | None
    status: ReportStatus
    created_at: datetime
    resolved_at: datetime | None
    reporter: UserRef | None
    resolver: UserRef | None
    # None when the content no longer exists (a hard-deleted thread takes its replies along).
    content: ContentSummary | None = None


class PaginatedReports(BaseModel):
    total: int
    items: list[ReportDetail]


def report_detail(report: Report, contents: dict[tuple[ContentType, int], Any]) -> ReportDetail:
    """A report (reporter and resolver loaded) with its content looked up in ``contents`` (from
    ``crud.reports.load_contents``)."""
    detail = ReportDetail.model_validate(report)
    content = contents.get((report.content_type, report.content_id))
    if content is not None:
        detail.content = content_summary(content)
    return detail
