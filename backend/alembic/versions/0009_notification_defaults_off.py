"""Member notifications off by default for new accounts (owner decision 2026-10-31).

``reply_to_my_thread``, ``comment_on_my_post``, ``reply_to_my_reply`` and
``moderation_decisions`` get ``server_default false``: a member now opts in on the Notifications
tab. ``admin_digest`` stays on and ``digest_frequency`` stays ``daily``.

Only the column defaults change. Existing rows are NOT updated: members who already have an
account keep the preferences they have (on, unless they switched them off). The downgrade
restores ``server_default true`` and likewise leaves the rows alone.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notification_preferences"
COLUMNS = ("reply_to_my_thread", "comment_on_my_post", "reply_to_my_reply", "moderation_decisions")


def upgrade() -> None:
    for column in COLUMNS:
        op.alter_column(
            TABLE,
            column,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("false"),
        )


def downgrade() -> None:
    for column in COLUMNS:
        op.alter_column(
            TABLE,
            column,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("true"),
        )
