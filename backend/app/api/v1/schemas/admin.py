"""Admin user-management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.auth import UserMe
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
