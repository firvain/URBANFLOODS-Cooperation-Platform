"""``moderation_note`` on posts and threads: the admin's note on the last rejection, shown to the
author (who can edit and resubmit the item); cleared when the item is approved. Replies and
comments are never reviewed, so they get no such column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("posts", "threads")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("moderation_note", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "moderation_note")
