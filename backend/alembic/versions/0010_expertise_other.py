"""Free-text "other" area of expertise (increment 7f).

Adds ``users.expertise_other VARCHAR(200) NULL``: a member whose field is not in
``expertise_tags`` can type it, as ``organisation_other`` does for organisations. It is shown on
the profile and the member card and matched by the directory search, but it is not a filter and
not used for suggested collaborators. No data change; existing members get ``NULL``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("expertise_other", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "expertise_other")
