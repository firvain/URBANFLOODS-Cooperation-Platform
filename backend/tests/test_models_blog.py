"""Increment 2a: blog schema (categories, tags, post_tags, posts, attachments, knowbase_links),
the users.avatar_attachment_id FK and the seeded categories.

All tests run against the session database migrated to head by ``conftest.py``. Every test works
inside the ``db_session`` transaction and only flushes, so the fixture's rollback leaves no rows
behind (ON DELETE behaviour is enforced by Postgres at statement time, so it is visible before
commit). Statements expected to fail run inside a SAVEPOINT so the transaction stays usable.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason, KbType
from app.db.models import Attachment, Category, KnowbaseLink, Post, Tag, User

SEEDED_CATEGORIES = {
    (CategoryKind.BLOG, "news"): ("News", False),
    (CategoryKind.BLOG, "best-practices"): ("Best practices", False),
    (CategoryKind.BLOG, "events"): ("Events", False),
    (CategoryKind.BLOG, "resources"): ("Resources", True),
    (CategoryKind.BLOG, "policy"): ("Policy and recommendations", False),
    (CategoryKind.FORUM, "general"): ("General discussion", False),
    (CategoryKind.FORUM, "measures"): ("Measures and solutions", False),
    (CategoryKind.FORUM, "early-warning"): ("Early warning and data", False),
    (CategoryKind.FORUM, "policy"): ("Policy and governance", False),
}


async def _make_user(db, email: str = "author@example.org") -> User:
    user = User(email=email, password_hash="not-a-real-hash", display_name="Author")
    db.add(user)
    await db.flush()
    return user


async def _category(db, kind: CategoryKind = CategoryKind.BLOG, slug: str = "news") -> Category:
    return (
        await db.execute(select(Category).where(Category.kind == kind, Category.slug == slug))
    ).scalar_one()


async def _make_post(db, *, slug: str = "first-post", **kwargs) -> Post:
    if "category_id" not in kwargs:
        kwargs["category_id"] = (await _category(db)).id
    post = Post(
        title=kwargs.pop("title", "Flood resilience in Kozani"),
        slug=slug,
        body_html=kwargs.pop("body_html", "<p>Nature-based solutions reduce flooding.</p>"),
        body_text=kwargs.pop("body_text", "Nature-based solutions reduce flooding."),
        **kwargs,
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)
    return post


async def _make_attachment(db, *, storage_path: str = "2026/10/a.webp", **kwargs) -> Attachment:
    attachment = Attachment(
        storage_path=storage_path,
        original_filename="photo.jpg",
        mime="image/webp",
        size_bytes=1234,
        width=800,
        height=600,
        alt_text="A flooded street",
        **kwargs,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def _expect_integrity_error(db, statement, params=None) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(statement, params or {})


# --- seed and enums ------------------------------------------------------------------------


async def test_migration_0004_seeds_categories(db_session):
    rows = (await db_session.execute(select(Category))).scalars().all()
    seeded = {(c.kind, c.slug): (c.name, c.admin_only) for c in rows}
    assert seeded == SEEDED_CATEGORIES

    resources = await _category(db_session, CategoryKind.BLOG, "resources")
    assert resources.admin_only is True
    assert resources.is_archived is False
    assert resources.name_i18n == {}
    assert resources.created_at is not None and resources.updated_at is not None

    blog_order = (
        await db_session.scalars(
            select(Category.slug)
            .where(Category.kind == CategoryKind.BLOG)
            .order_by(Category.sort_order)
        )
    ).all()
    assert blog_order == ["news", "best-practices", "events", "resources", "policy"]


async def test_enum_values_match_python_enums(db_session):
    expected = {
        "content_status": ContentStatus,
        "hidden_reason": HiddenReason,
        "category_kind": CategoryKind,
        "kb_type": KbType,
        "content_type": ContentType,
    }
    for pg_type, py_enum in expected.items():
        values = await db_session.scalar(text(f"SELECT enum_range(NULL::{pg_type})::text[]"))
        assert values == [member.value for member in py_enum], pg_type


# --- categories and tags -------------------------------------------------------------------


async def test_category_kind_slug_unique(db_session):
    # Same slug in another kind is fine (policy exists for both kinds already).
    db_session.add(Category(kind=CategoryKind.FORUM, slug="news", name="Forum news"))
    await db_session.flush()

    await _expect_integrity_error(
        db_session,
        text("INSERT INTO categories (kind, slug, name) VALUES ('blog', 'news', 'Dup')"),
    )


async def test_tag_slug_unique_and_defaults(db_session):
    tag = Tag(slug="nbs", name="NBS")
    db_session.add(tag)
    await db_session.flush()
    await db_session.refresh(tag)
    assert tag.usage_count == 0
    assert tag.created_at is not None

    await _expect_integrity_error(
        db_session, text("INSERT INTO tags (slug, name) VALUES ('nbs', 'Other')")
    )


async def test_tag_name_trigram_index_exists(db_session):
    indexdef = await db_session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_tags_name_trgm'")
    )
    assert indexdef is not None
    assert "gin" in indexdef and "gin_trgm_ops" in indexdef


# --- posts ---------------------------------------------------------------------------------


async def test_post_defaults(db_session):
    post = await _make_post(db_session)

    assert post.status is ContentStatus.PUBLISHED
    assert post.hidden_reason is None
    assert post.report_count == 0
    assert post.comment_count == 0
    assert post.locale == "en"
    assert post.deleted_at is None
    assert post.event_at is None and post.event_url is None
    assert post.created_at is not None and post.updated_at is not None


async def test_post_fts_generated_and_searchable(db_session):
    post = await _make_post(db_session, title="Flood maps for Macerata", body_text="Rain gauges.")
    other = await _make_post(
        db_session, slug="other", title="Partner meeting", body_text="Agenda only."
    )

    found = (
        await db_session.scalars(
            select(Post.id).where(Post.fts.op("@@")(text("plainto_tsquery('english', 'flood')")))
        )
    ).all()
    assert post.id in found
    assert other.id not in found

    # Body text is indexed too (weight B), and stemming applies ("gauge" ~ "gauges").
    by_body = await db_session.scalar(
        text("SELECT id FROM posts WHERE id = :id AND fts @@ plainto_tsquery('english', 'gauge')"),
        {"id": post.id},
    )
    assert by_body == post.id


async def test_post_fts_follows_updates(db_session):
    post = await _make_post(db_session, title="Draft", body_text="Nothing yet.")
    post.body_text = "Inundation modelling"
    await db_session.flush()

    hit = await db_session.scalar(
        text("SELECT id FROM posts WHERE fts @@ plainto_tsquery('english', 'inundation')")
    )
    assert hit == post.id


async def test_post_slug_unique(db_session):
    await _make_post(db_session, slug="same")
    category = await _category(db_session)

    await _expect_integrity_error(
        db_session,
        text(
            "INSERT INTO posts (category_id, title, slug, body_html, body_text) "
            "VALUES (:c, 't', 'same', '', '')"
        ),
        {"c": category.id},
    )


async def test_post_relationships(db_session):
    author = await _make_user(db_session)
    cover = await _make_attachment(db_session, uploader_id=author.id)
    nbs, gis = Tag(slug="nbs", name="NBS"), Tag(slug="gis", name="GIS")
    category = await _category(db_session, CategoryKind.BLOG, "events")
    post = Post(
        title="Workshop",
        slug="workshop",
        body_html="<p>Join us</p>",
        body_text="Join us",
        author=author,
        category=category,
        cover=cover,
        tags=[nbs, gis],
        event_at=datetime(2026, 12, 1, 9, tzinfo=UTC),
        event_url="https://example.org/workshop",
    )
    db_session.add(post)
    await db_session.flush()
    ids = (post.id, author.id, cover.id, nbs.id, category.id)
    db_session.expire_all()
    post_id, author_id, cover_id, nbs_id, category_id = ids

    loaded = await db_session.get(Post, post_id)
    await db_session.refresh(loaded, ["author", "category", "cover", "tags"])
    assert loaded.author.id == author_id
    assert loaded.category.slug == "events"
    assert loaded.cover.id == cover_id
    assert [t.slug for t in loaded.tags] == ["gis", "nbs"]  # ordered by name
    assert loaded.event_at == datetime(2026, 12, 1, 9, tzinfo=UTC)

    tag = await db_session.get(Tag, nbs_id)
    await db_session.refresh(tag, ["posts"])
    assert [p.id for p in tag.posts] == [post_id]

    events = await db_session.get(Category, category_id)
    await db_session.refresh(events, ["posts"])
    assert post_id in {p.id for p in events.posts}


async def test_category_delete_restricted_while_posts_exist(db_session):
    category = Category(kind=CategoryKind.BLOG, slug="temp", name="Temp")
    db_session.add(category)
    await db_session.flush()
    await _make_post(db_session, category_id=category.id)

    await _expect_integrity_error(db_session, delete(Category).where(Category.id == category.id))


async def test_user_delete_sets_post_author_and_approver_null(db_session):
    author = await _make_user(db_session)
    admin = await _make_user(db_session, email="admin@example.org")
    post = await _make_post(
        db_session, author_id=author.id, approved_by=admin.id, approved_at=datetime.now(UTC)
    )

    await db_session.execute(delete(User).where(User.id.in_([author.id, admin.id])))

    row = (
        await db_session.execute(
            text("SELECT author_id, approved_by FROM posts WHERE id = :id"), {"id": post.id}
        )
    ).one()
    assert row.author_id is None
    assert row.approved_by is None


async def test_attachment_delete_sets_cover_and_avatar_null(db_session):
    user = await _make_user(db_session)
    attachment = await _make_attachment(db_session, uploader_id=user.id)
    user.avatar_attachment_id = attachment.id
    post = await _make_post(db_session, cover_attachment_id=attachment.id)

    await db_session.execute(delete(Attachment).where(Attachment.id == attachment.id))

    cover = await db_session.scalar(
        text("SELECT cover_attachment_id FROM posts WHERE id = :id"), {"id": post.id}
    )
    avatar = await db_session.scalar(
        text("SELECT avatar_attachment_id FROM users WHERE id = :id"), {"id": user.id}
    )
    assert cover is None
    assert avatar is None


async def test_user_avatar_relationship_and_uploader_set_null(db_session):
    # User and avatar created in one flush: the user <-> attachment FK cycle must not break it.
    user = User(email="avatar@example.org", password_hash="x", display_name="Avatar")
    avatar = Attachment(
        uploader=user,
        storage_path="2026/10/avatar.webp",
        original_filename="me.png",
        mime="image/webp",
        size_bytes=10,
        width=48,
        height=48,
        alt_text="Portrait",
    )
    user.avatar = avatar
    db_session.add_all([user, avatar])
    await db_session.flush()
    user_id, avatar_id = user.id, avatar.id
    assert avatar.uploader_id == user_id
    db_session.expire_all()

    loaded = await db_session.get(User, user_id)
    await db_session.refresh(loaded, ["avatar"])
    assert loaded.avatar.id == avatar_id

    await db_session.execute(delete(User).where(User.id == user_id))
    uploader = await db_session.scalar(
        text("SELECT uploader_id FROM attachments WHERE id = :id"), {"id": avatar_id}
    )
    assert uploader is None


async def test_attachment_storage_path_unique(db_session):
    await _make_attachment(db_session, storage_path="2026/10/dup.webp")

    await _expect_integrity_error(
        db_session,
        text(
            "INSERT INTO attachments (storage_path, original_filename, mime, size_bytes, width, "
            "height, alt_text) VALUES ('2026/10/dup.webp', 'x', 'image/webp', 1, 1, 1, 'x')"
        ),
    )


async def test_post_tags_cascade_on_post_and_tag_delete(db_session):
    tag_a, tag_b = Tag(slug="a", name="A"), Tag(slug="b", name="B")
    post = await _make_post(db_session, tags=[tag_a, tag_b])
    await _make_post(db_session, slug="second", tags=[tag_b])

    async def links() -> int:
        return await db_session.scalar(text("SELECT count(*) FROM post_tags"))

    assert await links() == 3

    await db_session.execute(delete(Post).where(Post.id == post.id))
    assert await links() == 1

    await db_session.execute(delete(Tag).where(Tag.id == tag_b.id))
    assert await links() == 0


# --- knowbase_links ------------------------------------------------------------------------


async def test_knowbase_link_defaults_and_unique(db_session):
    link = KnowbaseLink(
        content_type=ContentType.POST,
        content_id=1,
        kb_type=KbType.MEASURE,
        kb_id=42,
        cached_title_en="Retention ponds",
    )
    db_session.add(link)
    await db_session.flush()
    await db_session.refresh(link)
    assert link.sort_order == 0
    assert link.cached_at is not None
    assert link.cached_title_local is None

    # Same KB item on another content row, or another kb_type with the same id, is fine.
    db_session.add_all(
        [
            KnowbaseLink(
                content_type=ContentType.THREAD,
                content_id=1,
                kb_type=KbType.MEASURE,
                kb_id=42,
                cached_title_en="Retention ponds",
            ),
            KnowbaseLink(
                content_type=ContentType.POST,
                content_id=1,
                kb_type=KbType.DOCUMENT,
                kb_id=42,
                cached_title_en="Flood directive",
            ),
        ]
    )
    await db_session.flush()

    await _expect_integrity_error(
        db_session,
        text(
            "INSERT INTO knowbase_links (content_type, content_id, kb_type, kb_id, "
            "cached_title_en) VALUES ('post', 1, 'measure', 42, 'dup')"
        ),
    )


@pytest.mark.parametrize("content_type", ["reply", "comment"])
async def test_knowbase_link_content_type_check(db_session, content_type):
    await _expect_integrity_error(
        db_session,
        text(
            "INSERT INTO knowbase_links (content_type, content_id, kb_type, kb_id, "
            "cached_title_en) VALUES (CAST(:ct AS content_type), 1, 'document', 7, 't')"
        ),
        {"ct": content_type},
    )


# --- indexes and autogenerate --------------------------------------------------------------


async def test_post_indexes_exist(db_session):
    rows = (
        await db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'posts'")
        )
    ).all()
    defs = {name: definition for name, definition in rows}

    assert "USING gin (fts)" in defs["ix_posts_fts"]
    assert "gin_trgm_ops" in defs["ix_posts_title_trgm"]
    assert "(status, published_at DESC)" in defs["ix_posts_status_published_at"]
    assert "WHERE (event_at IS NOT NULL)" in defs["ix_posts_event_at"]
    for name in ("ix_posts_category_id", "ix_posts_author_id", "ix_posts_locale"):
        assert name in defs


async def test_autogenerate_is_clean_and_quiet(db_session):
    """No diff and no warnings (e.g. "Computed default on posts.fts cannot be modified")."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from app.db.models import Base

    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    conn = await db_session.connection()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert await conn.run_sync(diff) == []
