"""Explicit declarative models (SQLAlchemy 2 style: ``DeclarativeBase`` + ``Mapped[]``).

Postgres ENUM types are created and dropped by the Alembic migrations, never by the models, so
every enum column uses ``create_type=False``.

``knowbase_links`` and ``reports`` are polymorphic (``content_type`` + ``content_id``), so they
have no FK and no relationship to the content tables; query them by ``(content_type, content_id)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.enums import (
    CategoryKind,
    ContentType,
    DigestFrequency,
    KbType,
    OrganisationType,
    ReportReason,
    ReportStatus,
    TokenPurpose,
    UserRole,
)
from app.db.mixins import ContentMixin, SoftDeleteMixin, TimestampMixin, pg_enum

# Deterministic constraint names, so later migrations can ALTER/DROP them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


user_role_enum = pg_enum(UserRole, "user_role")
token_purpose_enum = pg_enum(TokenPurpose, "token_purpose")
organisation_type_enum = pg_enum(OrganisationType, "organisation_type")
digest_frequency_enum = pg_enum(DigestFrequency, "digest_frequency")
category_kind_enum = pg_enum(CategoryKind, "category_kind")
kb_type_enum = pg_enum(KbType, "kb_type")
content_type_enum = pg_enum(ContentType, "content_type")
report_reason_enum = pg_enum(ReportReason, "report_reason")
report_status_enum = pg_enum(ReportStatus, "report_status")

# posts.fts: English stems weighted by field (title A, body B) plus the unstemmed ('simple') title,
# so exact title words in any language still match. Must stay identical to migration 0004.
POST_FTS_SQL = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body_text, '')), 'B') || "
    "to_tsvector('simple', coalesce(title, ''))"
)
# threads.fts: same weighting as posts. Must stay identical to migration 0005.
THREAD_FTS_SQL = POST_FTS_SQL
# replies.fts: body only, English stems. Must stay identical to migration 0005.
REPLY_FTS_SQL = "to_tsvector('english', coalesce(body_text, ''))"


class Organisation(TimestampMixin, Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)  # ISO alpha-2
    type: Mapped[OrganisationType] = mapped_column(organisation_type_enum, nullable=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_partner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class ExpertiseTag(Base):
    """Controlled vocabulary of expertise areas (seeded by migration 0003; English labels)."""

    __tablename__ = "expertise_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


user_expertise = Table(
    "user_expertise",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("expertise_tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_user_expertise_tag_id", "tag_id"),
)


class User(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_active", "id", postgresql_where=text("is_active")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organisation_other: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    locale: Mapped[str] = mapped_column(String(5), nullable=False, server_default=text("'en'"))
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    # users <-> attachments reference each other (avatar / uploader): use_alter breaks the cycle
    # for metadata DDL ordering, post_update on ``avatar`` breaks it for the ORM flush.
    avatar_attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    role: Mapped[UserRole] = mapped_column(
        user_role_enum, nullable=False, server_default=text("'member'"), index=True
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    trusted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    show_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    show_in_directory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    organisation: Mapped[Organisation | None] = relationship()
    expertise: Mapped[list[ExpertiseTag]] = relationship(
        secondary=user_expertise,
        order_by=[ExpertiseTag.sort_order, ExpertiseTag.id],
        passive_deletes=True,
    )
    notification_preferences: Mapped[NotificationPreference | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    avatar: Mapped[Attachment | None] = relationship(
        foreign_keys=[avatar_attachment_id], post_update=True
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class EmailToken(Base):
    __tablename__ = "email_tokens"
    __table_args__ = (Index("ix_email_tokens_user_id_purpose", "user_id", "purpose"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[TokenPurpose] = mapped_column(token_purpose_enum, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    new_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship()


class NotificationPreference(Base):
    """One row per user. The four member notifications are opt-in (off for new accounts since
    migration 0009, owner decision 2026-10-31); the admin digest is on by default."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    reply_to_my_thread: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    comment_on_my_post: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    reply_to_my_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    admin_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    moderation_decisions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    digest_frequency: Mapped[DigestFrequency] = mapped_column(
        digest_frequency_enum, nullable=False, server_default=text("'daily'")
    )

    user: Mapped[User] = relationship(back_populates="notification_preferences")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_target", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # ``metadata`` is reserved on declarative classes, hence the attribute name.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    actor: Mapped[User | None] = relationship()


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("kind", "slug", name="uq_categories_kind_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[CategoryKind] = mapped_column(category_kind_enum, nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional translations keyed by locale ({"el": "..."}); ``name`` is the English fallback.
    name_i18n: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Only admins may create content in this category (e.g. blog "resources").
    admin_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # ON DELETE RESTRICT: never let the ORM null out posts.category_id; the DB refuses instead.
    posts: Mapped[list[Post]] = relationship(back_populates="category", passive_deletes="all")
    threads: Mapped[list[Thread]] = relationship(back_populates="category", passive_deletes="all")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index(
            "ix_tags_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    posts: Mapped[list[Post]] = relationship(
        secondary=lambda: post_tags, back_populates="tags", passive_deletes=True
    )
    threads: Mapped[list[Thread]] = relationship(
        secondary=lambda: thread_tags, back_populates="tags", passive_deletes=True
    )


post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_post_tags_tag_id", "tag_id"),
)


class Attachment(Base):
    """An uploaded image (re-encoded to WebP); paths are relative to ``UPLOAD_DIR``."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    storage_path: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    thumb_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    alt_text: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    uploader: Mapped[User | None] = relationship(foreign_keys=[uploader_id])


class Post(TimestampMixin, SoftDeleteMixin, ContentMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_fts", "fts", postgresql_using="gin"),
        Index(
            "ix_posts_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_posts_status_published_at", "status", text("published_at DESC")),
        Index("ix_posts_event_at", "event_at", postgresql_where=text("event_at IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    excerpt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True
    )
    locale: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default=text("'en'"), index=True
    )
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The admin's note on the last rejection (plain text), shown to the author; cleared when the
    # item is approved. Replies and comments are never reviewed, so they have no such column.
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Generated by Postgres; deferred so ordinary loads do not ship the tsvector.
    fts: Mapped[str] = mapped_column(
        TSVECTOR, Computed(POST_FTS_SQL, persisted=True), nullable=True, deferred=True
    )

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    category: Mapped[Category] = relationship(back_populates="posts")
    cover: Mapped[Attachment | None] = relationship(foreign_keys=[cover_attachment_id])
    tags: Mapped[list[Tag]] = relationship(
        secondary=post_tags,
        back_populates="posts",
        order_by=lambda: Tag.name,
        passive_deletes=True,
    )
    # ON DELETE CASCADE: the ORM deletes loaded comments, Postgres the rest.
    comments: Mapped[list[Comment]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: (Comment.created_at, Comment.id),
    )


thread_tags = Table(
    "thread_tags",
    Base.metadata,
    Column("thread_id", ForeignKey("threads.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_thread_tags_tag_id", "tag_id"),
)


class Thread(TimestampMixin, SoftDeleteMixin, ContentMixin, Base):
    """A forum thread. ``category_id`` must point at a ``forum`` category (checked in crud).

    ``reply_count`` (published replies) and ``last_activity_at`` (bumped by each published reply)
    are maintained by the ``replies_reply_count`` trigger from migration 0005; refresh to read.
    """

    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_fts", "fts", postgresql_using="gin"),
        Index(
            "ix_threads_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_threads_listing",
            "status",
            text("is_pinned DESC"),
            text("last_activity_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    locale: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default=text("'en'"), index=True
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The admin's note on the last rejection (plain text), shown to the author; cleared when the
    # item is approved. Replies and comments are never reviewed, so they have no such column.
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    fts: Mapped[str] = mapped_column(
        TSVECTOR, Computed(THREAD_FTS_SQL, persisted=True), nullable=True, deferred=True
    )

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    category: Mapped[Category] = relationship(back_populates="threads")
    tags: Mapped[list[Tag]] = relationship(
        secondary=thread_tags,
        back_populates="threads",
        order_by=lambda: Tag.name,
        passive_deletes=True,
    )
    # ON DELETE CASCADE: the ORM deletes loaded replies, Postgres the rest.
    replies: Mapped[list[Reply]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: (Reply.created_at, Reply.id),
    )


class Reply(TimestampMixin, SoftDeleteMixin, ContentMixin, Base):
    """A reply in a thread, optionally to a top-level reply of the same thread (one level only:
    enforced by the ``replies_one_level`` trigger, which raises ``replies.nesting``)."""

    __tablename__ = "replies"
    __table_args__ = (
        Index("ix_replies_thread_id_status_created_at", "thread_id", "status", "created_at"),
        Index("ix_replies_fts", "fts", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # ON DELETE SET NULL: children of a hard-deleted reply survive as top-level replies.
    parent_reply_id: Mapped[int | None] = mapped_column(
        ForeignKey("replies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fts: Mapped[str] = mapped_column(
        TSVECTOR, Computed(REPLY_FTS_SQL, persisted=True), nullable=True, deferred=True
    )

    thread: Mapped[Thread] = relationship(back_populates="replies")
    author: Mapped[User | None] = relationship()
    parent: Mapped[Reply | None] = relationship(back_populates="children", remote_side=[id])
    children: Mapped[list[Reply]] = relationship(
        back_populates="parent",
        passive_deletes=True,
        order_by=lambda: (Reply.created_at, Reply.id),
    )


class Comment(TimestampMixin, SoftDeleteMixin, ContentMixin, Base):
    """A comment on a blog post. ``posts.comment_count`` (published comments) is maintained by
    the ``comments_comment_count`` trigger from migration 0005."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_post_id_status_created_at", "post_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    post: Mapped[Post] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship()


class KnowbaseLink(Base):
    """A post/thread's link to a KNOWBASE document or measure, with its cached titles."""

    __tablename__ = "knowbase_links"
    __table_args__ = (
        UniqueConstraint(
            "content_type", "content_id", "kb_type", "kb_id", name="uq_knowbase_links_content"
        ),
        CheckConstraint("content_type IN ('post', 'thread')", name="content_type"),
        Index("ix_knowbase_links_kb_type_kb_id", "kb_type", "kb_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_type: Mapped[ContentType] = mapped_column(content_type_enum, nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_type: Mapped[KbType] = mapped_column(kb_type_enum, nullable=False)
    kb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_title_en: Mapped[str] = mapped_column(Text, nullable=False)
    cached_title_local: Mapped[str | None] = mapped_column(Text, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class Report(Base):
    """A member's report of a post, thread, reply or comment (polymorphic: no FK to the content).

    One report per reporter per item (``uq_reports_reporter_content``); an anonymised reporter
    (``reporter_id`` NULL) never blocks anything, since Postgres treats NULLs as distinct.

    No trigger here: the content's ``report_count`` and the auto-hide at
    ``REPORT_AUTO_HIDE_THRESHOLD`` distinct reporters are maintained by ``crud/reports.py``.
    """

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "content_type", "content_id", name="uq_reports_reporter_content"
        ),
        Index("ix_reports_status_created_at", "status", "created_at"),
        Index("ix_reports_content_type_content_id", "content_type", "content_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    reporter_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content_type: Mapped[ContentType] = mapped_column(content_type_enum, nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[ReportReason] = mapped_column(report_reason_enum, nullable=False)
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        report_status_enum, nullable=False, server_default=text("'open'")
    )
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    reporter: Mapped[User | None] = relationship(foreign_keys=[reporter_id])
    resolver: Mapped[User | None] = relationship(foreign_keys=[resolved_by])


class DigestRun(Base):
    """One run of an email digest job (``kind`` e.g. ``admin_daily``); the latest run of a kind
    gives the next window's start."""

    __tablename__ = "digest_runs"
    __table_args__ = (Index("ix_digest_runs_kind_ran_at", "kind", text("ran_at DESC")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
