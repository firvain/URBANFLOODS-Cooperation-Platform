"""Forum schema: threads (with the generated ``fts`` column), thread_tags, replies (one-level
nesting trigger) and post comments, plus the triggers that keep ``threads.reply_count``,
``threads.last_activity_at`` and ``posts.comment_count`` in step.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types already exist (created by 0004); reuse them, never create or drop them here.
CONTENT_STATUS = postgresql.ENUM(name="content_status", create_type=False)
HIDDEN_REASON = postgresql.ENUM(name="hidden_reason", create_type=False)

# Same expressions as app.db.models.THREAD_FTS_SQL / REPLY_FTS_SQL (copied: migrations are frozen).
THREAD_FTS_SQL = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body_text, '')), 'B') || "
    "to_tsvector('simple', coalesce(title, ''))"
)
REPLY_FTS_SQL = "to_tsvector('english', coalesce(body_text, ''))"

# One level of nesting: a reply's parent must be a top-level reply of the same thread, a reply
# cannot be its own parent, and a reply that has children cannot become a child (or leave its
# children's thread). check_violation (23514) so drivers surface it as an integrity error.
REPLIES_ONE_LEVEL_FN = """
CREATE OR REPLACE FUNCTION replies_one_level() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_thread integer;
    parent_parent bigint;
BEGIN
    IF NEW.parent_reply_id IS NOT NULL THEN
        IF NEW.parent_reply_id = NEW.id THEN
            RAISE EXCEPTION 'replies.nesting' USING ERRCODE = 'check_violation';
        END IF;
        SELECT thread_id, parent_reply_id INTO parent_thread, parent_parent
          FROM replies WHERE id = NEW.parent_reply_id;
        -- A missing parent is left to the foreign key.
        IF FOUND AND (parent_parent IS NOT NULL OR parent_thread <> NEW.thread_id) THEN
            RAISE EXCEPTION 'replies.nesting' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP = 'UPDATE' AND EXISTS (
        SELECT 1 FROM replies c
         WHERE c.parent_reply_id = NEW.id
           AND (NEW.parent_reply_id IS NOT NULL OR c.thread_id <> NEW.thread_id)
    ) THEN
        RAISE EXCEPTION 'replies.nesting' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$
"""
REPLIES_ONE_LEVEL_TRIGGER = """
CREATE TRIGGER replies_one_level
BEFORE INSERT OR UPDATE OF parent_reply_id, thread_id ON replies
FOR EACH ROW EXECUTE FUNCTION replies_one_level()
"""

# threads.reply_count = published replies, recomputed (not incremented) so it never drifts; a
# published insert also bumps threads.last_activity_at.
REPLIES_REPLY_COUNT_FN = """
CREATE OR REPLACE FUNCTION replies_reply_count() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        UPDATE threads
           SET reply_count = (SELECT count(*) FROM replies
                               WHERE thread_id = OLD.thread_id AND status = 'published')
         WHERE id = OLD.thread_id;
    END IF;
    IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.thread_id <> OLD.thread_id) THEN
        UPDATE threads
           SET reply_count = (SELECT count(*) FROM replies
                               WHERE thread_id = NEW.thread_id AND status = 'published'),
               last_activity_at = CASE
                   WHEN TG_OP = 'INSERT' AND NEW.status = 'published' THEN now()
                   ELSE last_activity_at
               END
         WHERE id = NEW.thread_id;
    END IF;
    RETURN NULL;
END;
$$
"""
REPLIES_REPLY_COUNT_TRIGGER = """
CREATE TRIGGER replies_reply_count
AFTER INSERT OR UPDATE OF status, thread_id OR DELETE ON replies
FOR EACH ROW EXECUTE FUNCTION replies_reply_count()
"""

# posts.comment_count = published comments.
COMMENTS_COMMENT_COUNT_FN = """
CREATE OR REPLACE FUNCTION comments_comment_count() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        UPDATE posts
           SET comment_count = (SELECT count(*) FROM comments
                                 WHERE post_id = OLD.post_id AND status = 'published')
         WHERE id = OLD.post_id;
    END IF;
    IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.post_id <> OLD.post_id) THEN
        UPDATE posts
           SET comment_count = (SELECT count(*) FROM comments
                                 WHERE post_id = NEW.post_id AND status = 'published')
         WHERE id = NEW.post_id;
    END IF;
    RETURN NULL;
END;
$$
"""
COMMENTS_COMMENT_COUNT_TRIGGER = """
CREATE TRIGGER comments_comment_count
AFTER INSERT OR UPDATE OF status, post_id OR DELETE ON comments
FOR EACH ROW EXECUTE FUNCTION comments_comment_count()
"""

# (trigger, table, function) — dropped in reverse order by downgrade().
TRIGGERS = (
    ("replies_one_level", "replies", "replies_one_level"),
    ("replies_reply_count", "replies", "replies_reply_count"),
    ("comments_comment_count", "comments", "comments_comment_count"),
)


def _content_columns() -> list[sa.Column]:
    """ContentMixin + TimestampMixin + SoftDeleteMixin."""
    return [
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", CONTENT_STATUS, server_default=sa.text("'published'"), nullable=False),
        sa.Column("hidden_reason", HIDDEN_REASON, nullable=True),
        sa.Column("report_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("locale", sa.String(length=5), server_default=sa.text("'en'"), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reply_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_content_columns(),
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(THREAD_FTS_SQL, persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_threads_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_threads_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_threads_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads")),
        sa.UniqueConstraint("slug", name=op.f("uq_threads_slug")),
    )
    op.create_index("ix_threads_fts", "threads", ["fts"], postgresql_using="gin")
    # pg_trgm comes from 0001.
    op.execute("CREATE INDEX ix_threads_title_trgm ON threads USING gin (title gin_trgm_ops)")
    op.create_index(
        "ix_threads_listing",
        "threads",
        ["status", sa.text("is_pinned DESC"), sa.text("last_activity_at DESC")],
    )
    op.create_index(op.f("ix_threads_category_id"), "threads", ["category_id"])
    op.create_index(op.f("ix_threads_author_id"), "threads", ["author_id"])
    op.create_index(op.f("ix_threads_locale"), "threads", ["locale"])

    op.create_table(
        "thread_tags",
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
            name=op.f("fk_thread_tags_thread_id_threads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_thread_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("thread_id", "tag_id", name=op.f("pk_thread_tags")),
    )
    op.create_index("ix_thread_tags_tag_id", "thread_tags", ["tag_id"])

    op.create_table(
        "replies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("parent_reply_id", sa.BigInteger(), nullable=True),
        *_content_columns(),
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(REPLY_FTS_SQL, persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
            name=op.f("fk_replies_thread_id_threads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_replies_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_reply_id"],
            ["replies.id"],
            name=op.f("fk_replies_parent_reply_id_replies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_replies")),
    )
    op.create_index(
        "ix_replies_thread_id_status_created_at",
        "replies",
        ["thread_id", "status", "created_at"],
    )
    op.create_index(op.f("ix_replies_parent_reply_id"), "replies", ["parent_reply_id"])
    op.create_index(op.f("ix_replies_author_id"), "replies", ["author_id"])
    op.create_index("ix_replies_fts", "replies", ["fts"], postgresql_using="gin")

    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        *_content_columns(),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_comments_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(
        "ix_comments_post_id_status_created_at",
        "comments",
        ["post_id", "status", "created_at"],
    )
    op.create_index(op.f("ix_comments_author_id"), "comments", ["author_id"])

    # Triggers are not autogenerated (and not compared), so they live here only.
    op.execute(REPLIES_ONE_LEVEL_FN)
    op.execute(REPLIES_ONE_LEVEL_TRIGGER)
    op.execute(REPLIES_REPLY_COUNT_FN)
    op.execute(REPLIES_REPLY_COUNT_TRIGGER)
    op.execute(COMMENTS_COMMENT_COUNT_FN)
    op.execute(COMMENTS_COMMENT_COUNT_TRIGGER)


def downgrade() -> None:
    for trigger, table, function in reversed(TRIGGERS):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    op.drop_table("comments")
    op.drop_table("replies")
    op.drop_table("thread_tags")
    op.drop_table("threads")
