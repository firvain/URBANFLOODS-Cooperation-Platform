"""Blog schema: categories (seeded for blog and forum), tags, post_tags, attachments, posts (with
the generated ``fts`` column), knowbase_links, their enum types, and the users.avatar_attachment_id
FK to attachments.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types are owned by this migration (models use create_type=False). Values and order must
# match app/db/enums.py; tests/test_models_blog.py checks this.
CONTENT_STATUS = postgresql.ENUM(
    "pending", "published", "hidden", "deleted", name="content_status", create_type=False
)
HIDDEN_REASON = postgresql.ENUM(
    "auto_reports", "admin", "rejected", name="hidden_reason", create_type=False
)
CATEGORY_KIND = postgresql.ENUM("blog", "forum", name="category_kind", create_type=False)
KB_TYPE = postgresql.ENUM("document", "measure", name="kb_type", create_type=False)
CONTENT_TYPE = postgresql.ENUM(
    "post", "thread", "reply", "comment", name="content_type", create_type=False
)
ENUMS = (CONTENT_STATUS, HIDDEN_REASON, CATEGORY_KIND, KB_TYPE, CONTENT_TYPE)

# Same expression as app.db.models.POST_FTS_SQL (copied, not imported: migrations are frozen).
POST_FTS_SQL = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body_text, '')), 'B') || "
    "to_tsvector('simple', coalesce(title, ''))"
)

# Seed: English names; the frontend translates by (kind, slug). sort_order is the 1-based
# position within the kind. Only admins may post in blog "resources".
CATEGORY_ROWS: list[tuple[str, str, str, bool]] = [
    ("blog", "news", "News", False),
    ("blog", "best-practices", "Best practices", False),
    ("blog", "events", "Events", False),
    ("blog", "resources", "Resources", True),
    ("blog", "policy", "Policy and recommendations", False),
    ("forum", "general", "General discussion", False),
    ("forum", "measures", "Measures and solutions", False),
    ("forum", "early-warning", "Early warning and data", False),
    ("forum", "policy", "Policy and governance", False),
]


def _categories() -> list[dict[str, object]]:
    positions: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for kind, slug, name, admin_only in CATEGORY_ROWS:
        positions[kind] = positions.get(kind, 0) + 1
        rows.append(
            {
                "kind": kind,
                "slug": slug,
                "name": name,
                "sort_order": positions[kind],
                "admin_only": admin_only,
            }
        )
    return rows


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

    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", CATEGORY_KIND, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "name_i18n",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("admin_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("kind", "slug", name="uq_categories_kind_slug"),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("usage_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("slug", name=op.f("uq_tags_slug")),
    )
    # pg_trgm comes from 0001.
    op.execute("CREATE INDEX ix_tags_name_trgm ON tags USING gin (name gin_trgm_ops)")

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column("thumb_path", sa.String(length=255), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
            name=op.f("fk_attachments_uploader_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("storage_path", name=op.f("uq_attachments_storage_path")),
    )
    op.create_index(op.f("ix_attachments_uploader_id"), "attachments", ["uploader_id"])
    op.create_index(op.f("ix_attachments_created_at"), "attachments", ["created_at"])

    op.create_foreign_key(
        op.f("fk_users_avatar_attachment_id_attachments"),
        "users",
        "attachments",
        ["avatar_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("excerpt", sa.String(length=500), nullable=True),
        sa.Column("cover_attachment_id", sa.Integer(), nullable=True),
        sa.Column("locale", sa.String(length=5), server_default=sa.text("'en'"), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_url", sa.Text(), nullable=True),
        sa.Column("comment_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        # ContentMixin
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", CONTENT_STATUS, server_default=sa.text("'published'"), nullable=False),
        sa.Column("hidden_reason", HIDDEN_REASON, nullable=True),
        sa.Column("report_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(POST_FTS_SQL, persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_posts_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_posts_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cover_attachment_id"],
            ["attachments.id"],
            name=op.f("fk_posts_cover_attachment_id_attachments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_posts_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
        sa.UniqueConstraint("slug", name=op.f("uq_posts_slug")),
    )
    op.create_index("ix_posts_fts", "posts", ["fts"], postgresql_using="gin")
    op.execute("CREATE INDEX ix_posts_title_trgm ON posts USING gin (title gin_trgm_ops)")
    op.create_index(
        "ix_posts_status_published_at", "posts", ["status", sa.text("published_at DESC")]
    )
    op.create_index(op.f("ix_posts_category_id"), "posts", ["category_id"])
    op.create_index(op.f("ix_posts_author_id"), "posts", ["author_id"])
    op.create_index(
        "ix_posts_event_at",
        "posts",
        ["event_at"],
        postgresql_where=sa.text("event_at IS NOT NULL"),
    )
    op.create_index(op.f("ix_posts_locale"), "posts", ["locale"])

    op.create_table(
        "post_tags",
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name=op.f("fk_post_tags_post_id_posts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_post_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_id", "tag_id", name=op.f("pk_post_tags")),
    )
    op.create_index("ix_post_tags_tag_id", "post_tags", ["tag_id"])

    op.create_table(
        "knowbase_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_type", CONTENT_TYPE, nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_type", KB_TYPE, nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=False),
        sa.Column("cached_title_en", sa.Text(), nullable=False),
        sa.Column("cached_title_local", sa.Text(), nullable=True),
        sa.Column(
            "cached_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Links hang off posts and threads only; replies and comments never carry them.
        sa.CheckConstraint(
            "content_type IN ('post', 'thread')", name=op.f("ck_knowbase_links_content_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowbase_links")),
        sa.UniqueConstraint(
            "content_type", "content_id", "kb_type", "kb_id", name="uq_knowbase_links_content"
        ),
    )
    op.create_index("ix_knowbase_links_kb_type_kb_id", "knowbase_links", ["kb_type", "kb_id"])

    op.bulk_insert(categories, _categories())


def downgrade() -> None:
    op.drop_table("knowbase_links")
    op.drop_table("post_tags")
    op.drop_table("posts")
    op.drop_constraint(
        op.f("fk_users_avatar_attachment_id_attachments"), "users", type_="foreignkey"
    )
    op.drop_table("attachments")
    op.drop_table("tags")
    op.drop_table("categories")

    bind = op.get_bind()
    for enum_type in reversed(ENUMS):
        enum_type.drop(bind, checkfirst=True)
