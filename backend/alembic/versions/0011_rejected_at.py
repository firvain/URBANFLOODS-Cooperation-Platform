"""``rejected_at`` on posts and threads: when an admin last rejected the item (cleared when it is
approved, kept when the author resubmits). The auto-approve sweep never approves an item that has
one, so a resubmitted edit always needs an admin, and the moderation queue flags resubmissions by
it (``moderation_note`` cannot tell, since a rejection may have no reason).

Existing rows are backfilled from the audit log: the latest ``moderation.reject`` row for the
item, when it is later than the item's approval (or the item was never approved).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> the ``audit_log.target_type`` its rows are logged under (``ContentType`` values).
TABLES = {"posts": "post", "threads": "thread"}


def upgrade() -> None:
    for table, target_type in TABLES.items():
        op.add_column(table, sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(
            f"""
            UPDATE {table} AS c
            SET rejected_at = r.rejected_at
            FROM (
                SELECT target_id, max(created_at) AS rejected_at
                FROM audit_log
                WHERE action = 'moderation.reject' AND target_type = '{target_type}'
                GROUP BY target_id
            ) AS r
            WHERE r.target_id = c.id
              AND (c.approved_at IS NULL OR r.rejected_at > c.approved_at)
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "rejected_at")
