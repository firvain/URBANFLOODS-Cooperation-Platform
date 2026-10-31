"""Admin user-management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import UserMe
from app.api.v1.schemas.knowbase import KnowbaseStatus
from app.db.enums import UserRole


class AdminUserOut(UserMe):
    """A user as admins see it: the account fields plus moderation state."""

    is_active: bool
    last_login_at: datetime | None
    deleted_at: datetime | None


class AdminUserList(BaseModel):
    total: int
    items: list[AdminUserOut]


class AdminUserUpdate(BaseModel):
    """Partial update; each present field goes through the same rules (and audit action) as the
    matching ``/promote``, ``/demote``, ``/ban``, ``/unban``, ``/trust`` or ``/untrust``."""

    role: UserRole | None = None
    is_active: bool | None = None
    trusted: bool | None = None

    @field_validator("role", "is_active", "trusted")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be null")
        return value


# --- stats ------------------------------------------------------------------------------------


class UserStats(BaseModel):
    total: int
    verified: int
    trusted: int
    admins: int
    new_30d: int


class ContentStats(BaseModel):
    posts_published: int
    threads_published: int
    replies: int
    comments: int
    pending: int


class AdminStats(BaseModel):
    users: UserStats
    content: ContentStats
    reports_open: int
    # The same shape as ``GET /knowbase/status``.
    knowbase: KnowbaseStatus


class CacheClearResult(BaseModel):
    cleared: int


class DigestSendResult(BaseModel):
    """``POST /admin/digest/send``: how many admins got the digest and how many items it
    listed; ``sent`` is false (and the counts 0) when every email failed."""

    recipients: int
    items: int
    sent: bool
