"""Upload schemas. Storage paths stay internal; clients get URLs under ``UPLOAD_URL_PREFIX``."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings


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


class UploadList(BaseModel):
    total: int
    items: list[UploadOut]
