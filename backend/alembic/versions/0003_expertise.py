"""Partner matchmaking: expertise_tags (seeded controlled vocabulary), the user_expertise
junction, and the users.show_email / users.show_in_directory profile flags.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed: the 3rd project meeting's matchmaking vocabulary (docs/requirements-3rd-project-meeting.md).
# English labels; the frontend translates by slug. sort_order is the 1-based position.
EXPERTISE_ROWS: list[tuple[str, str]] = [
    ("hydrology", "Hydrology"),
    ("hydraulic-modelling", "Hydraulic modelling"),
    ("flood-risk-mapping", "Flood risk mapping"),
    ("early-warning-systems", "Early warning systems"),
    ("civil-protection", "Civil protection and emergency management"),
    ("urban-planning", "Urban and spatial planning"),
    ("nature-based-solutions", "Nature-based solutions"),
    ("green-blue-infrastructure", "Green and blue infrastructure"),
    ("water-supply-sewerage", "Water supply and sewerage"),
    ("river-basin-management", "River basin management"),
    ("coastal-management", "Coastal management"),
    ("climate-adaptation", "Climate change adaptation"),
    ("policy-governance", "Policy and governance"),
    ("gis-remote-sensing", "GIS and remote sensing"),
    ("data-science-dss", "Data science and decision support systems"),
    ("environmental-engineering", "Environmental engineering"),
    ("community-engagement", "Community engagement and communication"),
    ("education-training", "Education and training"),
    ("agriculture-irrigation", "Agriculture and irrigation"),
    ("economics-insurance", "Economics and insurance"),
    ("meteorology", "Meteorology and climatology"),
    ("ecology-biodiversity", "Ecology and biodiversity"),
]
EXPERTISE_TAGS: list[dict[str, object]] = [
    {"slug": slug, "label": label, "sort_order": position, "is_active": True}
    for position, (slug, label) in enumerate(EXPERTISE_ROWS, start=1)
]


def upgrade() -> None:
    expertise_tags = op.create_table(
        "expertise_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expertise_tags")),
        sa.UniqueConstraint("slug", name=op.f("uq_expertise_tags_slug")),
    )

    op.create_table(
        "user_expertise",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_expertise_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["expertise_tags.id"],
            name=op.f("fk_user_expertise_tag_id_expertise_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "tag_id", name=op.f("pk_user_expertise")),
    )
    op.create_index("ix_user_expertise_tag_id", "user_expertise", ["tag_id"])

    op.add_column(
        "users",
        sa.Column("show_email", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "show_in_directory", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )

    op.bulk_insert(expertise_tags, EXPERTISE_TAGS)


def downgrade() -> None:
    op.drop_column("users", "show_in_directory")
    op.drop_column("users", "show_email")
    op.drop_table("user_expertise")
    op.drop_table("expertise_tags")
