"""Column mixins shared by declarative models, and the ``pg_enum`` helper used with them."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import ContentStatus, HiddenReason


def pg_enum(enum_cls: type[enum.Enum], name: str) -> ENUM:
    """PG ENUM bound to a Python enum, storing values (not member names); type owned by Alembic."""
    return ENUM(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
        create_type=False,
    )


content_status_enum = pg_enum(ContentStatus, "content_status")
hidden_reason_enum = pg_enum(HiddenReason, "hidden_reason")


class TimestampMixin:
    """``created_at`` / ``updated_at`` set by the database; ``updated_at`` bumped on ORM update."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Soft delete: rows are never removed, ``deleted_at`` is set instead."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContentMixin:
    """User-generated content: sanitised HTML, its plain text (for FTS), and moderation state.

    ``body_html`` must come from ``services/sanitize.py``; ``body_text`` is derived from it.
    """

    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ContentStatus] = mapped_column(
        content_status_enum, nullable=False, server_default=text("'published'")
    )
    hidden_reason: Mapped[HiddenReason | None] = mapped_column(hidden_reason_enum, nullable=True)
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
