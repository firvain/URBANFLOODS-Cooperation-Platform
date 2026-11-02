"""Upload schemas. Storage paths stay internal; clients get URLs under ``UPLOAD_URL_PREFIX``."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings
from app.db.enums import ContentStatus, ContentType


class UploadKind(StrEnum):
    IMAGE = "image"
    COVER = "cover"
    AVATAR = "avatar"


def upload_url(rel_path: str | None) -> str | None:
    """The public URL of a file stored at ``rel_path`` under ``UPLOAD_DIR``."""
    return f"{settings.UPLOAD_URL_PREFIX}/{rel_path}" if rel_path else None


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_path: str = Field(exclude=True)
    thumb_path: str | None = Field(default=None, exclude=True)
    width: int
    height: int
    size_bytes: int
    mime: str
    alt_text: str
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return f"{settings.UPLOAD_URL_PREFIX}/{self.storage_path}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def thumb_url(self) -> str | None:
        return upload_url(self.thumb_path)


class UploadUsage(BaseModel):
    """Content that uses an upload (cover or inline image), anyone's, any status. For a reply or
    comment, ``title``/``slug`` are those of the thread/post it belongs to."""

    model_config = ConfigDict(from_attributes=True)

    content_type: ContentType
    id: int
    title: str | None
    slug: str | None
    status: ContentStatus
    by_uploader: bool = Field(
        description="The content's author is the upload's uploader. Only such content (not "
        "deleted) keeps the uploader from deleting the image."
    )


class MyUploadOut(UploadOut):
    used_in: list[UploadUsage] = []


class UploadList(BaseModel):
    total: int
    items: list[MyUploadOut]
