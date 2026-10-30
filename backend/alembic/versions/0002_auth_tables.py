"""Auth tables: organisations (seeded with the 22 project partners), users, sessions,
email_tokens, notification_preferences, audit_log, and their enum types.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types are owned by this migration (models use create_type=False). Values and order must
# match app/db/enums.py; tests/test_models_auth.py checks this.
USER_ROLE = postgresql.ENUM("member", "admin", "superadmin", name="user_role", create_type=False)
TOKEN_PURPOSE = postgresql.ENUM(
    "verify_email", "reset_password", "change_email", name="token_purpose", create_type=False
)
ORGANISATION_TYPE = postgresql.ENUM(
    "PP", "AP", "other", name="organisation_type", create_type=False
)
DIGEST_FREQUENCY = postgresql.ENUM("daily", "weekly", name="digest_frequency", create_type=False)
ENUMS = (USER_ROLE, TOKEN_PURPOSE, ORGANISATION_TYPE, DIGEST_FREQUENCY)

# Seed: docs/partners.md (application form IPA-ADRION00374 v4.0, section B).
# type is PP for the lead partner and the project partners, AP for associated partners.
# sort_order is the "#" column; website None means NULL; is_partner is true for all 22.
# fmt: off
PARTNER_COLUMNS = ("sort_order", "type", "short_name", "name", "country", "website")
PARTNER_ROWS: list[tuple[int, str, str, str, str, str | None]] = [
    (1, "PP", "UOWM", "University of Western Macedonia", "GR", "https://www.uowm.gr/en/"),
    (2, "PP", "HEIS", "Hydro-Engineering Institute Sarajevo", "BA", "http://heis.ba/"),
    (3, "PP", "DCMS", "Development Centre Murska Sobota", "SI", "https://www.rcms.si"),
    (4, "PP", "MC", "Macerata Municipality", "IT", "https://www.comune.macerata.it/"),
    (5, "PP", "RDA Backa", "Regional Development Agency Backa Ltd. Novi Sad", "RS", "https://www.rda-backa.rs"),  # noqa: E501
    (6, "PP", "DEYAK", "Municipal Enterprise for Water Supply and Sewerage of Kozani", "GR", "https://www.deyakozanis.gr/"),  # noqa: E501
    (7, "PP", "HydrowaterAL", "Hydrowater-Albania", "AL", "https://hydrowateralbania.com/"),
    (8, "PP", "RDA Porin", "Rijeka Development Agency PORIN Ltd.", "HR", "https://www.porin.hr"),
    (9, "PP", "FCSE-UKIM", "Ss. Cyril and Methodius University in Skopje (Faculty of Computer Science and Engineering)", "MK", "https://ukim.edu.mk"),  # noqa: E501
    (10, "PP", "SVIMED", "SVI.MED. EuroMediterranean Center for the Sustainable Development", "IT", "https://www.svimed.eu"),  # noqa: E501
    (11, "PP", "CKM", "Center for Knowledge Management", "MK", "https://www.knowledge-center.org"),
    (12, "AP", "Scicli", "Municipality of Scicli", "IT", None),
    (13, "AP", "Modica", "Municipality of Modica", "IT", None),
    (14, "AP", "ARSO", "Slovenian Environment Agency (ARSO)", "SI", None),
    (15, "AP", "AVP Jadransko more", "Agency for Watershed of the Adriatic Sea", "BA", None),
    (16, "AP", "SHUKALB", "Water Supply and Sewerage Association of Albania", "AL", None),
    (17, "AP", "MEEN GDW", "Ministry of Environment and Energy, General Directorate for Water", "GR", None),  # noqa: E501
    (18, "AP", "Vode Vojvodine", 'Public Water Management Company "Vode Vojvodine"', "RS", None),
    (19, "AP", "Kozani", "Municipality of Kozani", "GR", None),
    (20, "AP", "CMC", "Center for Crisis Management", "MK", None),
    (21, "AP", "TEMENUS", "Institute of Sustainable Development and Management of Natural Resources, UCRI TEMENUS, UOWM", "GR", None),  # noqa: E501
    (22, "AP", "Priroda", "Public Institution for Protected Area Management in the Primorje-Gorski Kotar County", "HR", None),  # noqa: E501
]
# fmt: on
PARTNERS: list[dict[str, object]] = [
    {**dict(zip(PARTNER_COLUMNS, row, strict=True)), "is_partner": True} for row in PARTNER_ROWS
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind, checkfirst=True)

    organisations = op.create_table(
        "organisations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("type", ORGANISATION_TYPE, nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("is_partner", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisations")),
        sa.UniqueConstraint("name", name=op.f("uq_organisations_name")),
    )
    op.create_index(op.f("ix_organisations_country"), "organisations", ["country"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("organisation_other", sa.String(length=200), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("locale", sa.String(length=5), server_default=sa.text("'en'"), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        # FK to attachments.id is added in increment 2a.
        sa.Column("avatar_attachment_id", sa.Integer(), nullable=True),
        sa.Column("role", USER_ROLE, server_default=sa.text("'member'"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("trusted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_users_organisation_id_organisations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"])
    op.create_index(op.f("ix_users_trusted_at"), "users", ["trusted_at"])
    op.create_index(op.f("ix_users_organisation_id"), "users", ["organisation_id"])
    op.create_index("ix_users_active", "users", ["id"], postgresql_where=sa.text("is_active"))

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])

    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", TOKEN_PURPOSE, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("new_email", postgresql.CITEXT(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_tokens_token_hash")),
    )
    op.create_index("ix_email_tokens_user_id_purpose", "email_tokens", ["user_id", "purpose"])

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "reply_to_my_thread", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "comment_on_my_post", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "reply_to_my_reply", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("admin_digest", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "digest_frequency",
            DIGEST_FREQUENCY,
            server_default=sa.text("'daily'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"])

    op.bulk_insert(organisations, PARTNERS)


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("notification_preferences")
    op.drop_table("email_tokens")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_table("organisations")

    bind = op.get_bind()
    for enum_type in reversed(ENUMS):
        enum_type.drop(bind, checkfirst=True)
