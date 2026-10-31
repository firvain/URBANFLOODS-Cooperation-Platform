"""Moderation schema: ``reports`` (polymorphic, one per reporter per item) and ``digest_runs``,
plus the ``report_reason`` / ``report_status`` enum types. No triggers: report counting and
auto-hide live in crud.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Owned by this migration: created in upgrade(), dropped in downgrade().
REPORT_REASON = postgresql.ENUM(
    "spam", "abuse", "off_topic", "misinformation", "other", name="report_reason", create_type=False
)
REPORT_STATUS = postgresql.ENUM(
    "open", "resolved", "dismissed", name="report_status", create_type=False
)
ENUMS = (REPORT_REASON, REPORT_STATUS)

# Created by 0004; reused, never created or dropped here.
CONTENT_TYPE = postgresql.ENUM(name="content_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=True),
        sa.Column("content_type", CONTENT_TYPE, nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", REPORT_REASON, nullable=False),
        sa.Column("details", sa.String(length=1000), nullable=True),
        sa.Column("status", REPORT_STATUS, server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_reports_reporter_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_reports_resolved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint(
            "reporter_id", "content_type", "content_id", name="uq_reports_reporter_content"
        ),
    )
    op.create_index("ix_reports_status_created_at", "reports", ["status", "created_at"])
    op.create_index("ix_reports_content_type_content_id", "reports", ["content_type", "content_id"])

    op.create_table(
        "digest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "ran_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipients", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_digest_runs")),
    )
    op.create_index("ix_digest_runs_kind_ran_at", "digest_runs", ["kind", sa.text("ran_at DESC")])


def downgrade() -> None:
    op.drop_table("digest_runs")
    op.drop_table("reports")

    bind = op.get_bind()
    for enum_type in reversed(ENUMS):
        enum_type.drop(bind, checkfirst=True)
