"""Increment 3a: forum schema (threads, thread_tags, replies), post comments, the one-level reply
trigger and the reply/comment counter triggers (migration 0005).

Like ``test_models_blog.py``: every test runs inside the ``db_session`` transaction and only
flushes, so the fixture's rollback leaves no rows behind. Statements expected to fail run inside
a SAVEPOINT so the transaction stays usable. Counters are maintained by triggers, so they are
read back with ``refresh`` (or raw SQL), never from the identity map.
"""

from __future__ import annotations

import uuid
import warnings
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.enums import CategoryKind, ContentStatus, HiddenReason
from app.db.models import Category, Comment, Post, Reply, Tag, Thread, User
from tests.factories import (
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_tag,
    create_thread,
    create_user,
)

NESTING = "replies.nesting"
OLD = datetime(2020, 1, 1, tzinfo=UTC)


async def _forum_category(db, slug: str = "general") -> Category:
    return (
        await db.execute(
            select(Category).where(Category.kind == CategoryKind.FORUM, Category.slug == slug)
        )
    ).scalar_one()


async def _blog_category(db) -> Category:
    return (
        await db.execute(
            select(Category).where(Category.kind == CategoryKind.BLOG, Category.slug == "news")
        )
    ).scalar_one()


async def _thread(db, **kwargs) -> Thread:
    if "category_id" not in kwargs:
        kwargs["category_id"] = (await _forum_category(db)).id
    thread = await create_thread(db, **kwargs)
    await db.refresh(thread)
    return thread


async def _post(db, **kwargs) -> Post:
    post = await create_post(db, category_id=(await _blog_category(db)).id, **kwargs)
    await db.refresh(post)
    return post


async def _expect_integrity_error(db, statement, params=None) -> IntegrityError:
    with pytest.raises(IntegrityError) as info:
        async with db.begin_nested():
            await db.execute(statement, params or {})
    return info.value


async def _expect_nesting_error(db, statement, params=None) -> None:
    error = await _expect_integrity_error(db, statement, params)
    assert NESTING in str(error)


async def _reply_count(db, thread_id: int) -> int:
    return await db.scalar(
        text("SELECT reply_count FROM threads WHERE id = :id"), {"id": thread_id}
    )


async def _comment_count(db, post_id: int) -> int:
    return await db.scalar(text("SELECT comment_count FROM posts WHERE id = :id"), {"id": post_id})


def _insert_reply_sql() -> text:
    return text(
        "INSERT INTO replies (thread_id, parent_reply_id, body_html, body_text) "
        "VALUES (:thread, :parent, '<p>x</p>', 'x')"
    )


# --- threads -------------------------------------------------------------------------------


async def test_thread_defaults(db_session):
    thread = await _thread(db_session)

    assert thread.status is ContentStatus.PUBLISHED
    assert thread.hidden_reason is None
    assert thread.report_count == 0
    assert thread.reply_count == 0
    assert thread.is_pinned is False
    assert thread.is_locked is False
    assert thread.locale == "en"
    assert thread.deleted_at is None
    assert thread.approved_by is None and thread.approved_at is None
    assert thread.last_activity_at is not None
    assert thread.created_at is not None and thread.updated_at is not None


async def test_thread_fts_generated_and_searchable(db_session):
    thread = await _thread(db_session, title="Rain gauges in Kozani", body_text="Sensor networks.")
    other = await _thread(db_session, title="Partner meeting", body_text="Agenda only.")

    def match(query: str):
        return select(Thread.id).where(
            Thread.fts.op("@@")(text(f"plainto_tsquery('english', '{query}')"))
        )

    by_title = (await db_session.scalars(match("gauge"))).all()
    assert thread.id in by_title and other.id not in by_title

    by_body = (await db_session.scalars(match("network"))).all()
    assert thread.id in by_body and other.id not in by_body

    # The unstemmed 'simple' title is indexed too, so exact title words always match.
    simple = await db_session.scalar(
        text("SELECT id FROM threads WHERE id = :id AND fts @@ to_tsquery('simple', 'kozani')"),
        {"id": thread.id},
    )
    assert simple == thread.id


async def test_thread_slug_unique(db_session):
    await _thread(db_session, slug="same-thread")
    category = await _forum_category(db_session)

    await _expect_integrity_error(
        db_session,
        text(
            "INSERT INTO threads (category_id, title, slug, body_html, body_text) "
            "VALUES (:c, 't', 'same-thread', '', '')"
        ),
        {"c": category.id},
    )


async def test_thread_relationships(db_session):
    author = await create_user(db_session)
    category = await _forum_category(db_session, "measures")
    nbs, gis = Tag(slug="nbs-forum", name="NBS"), Tag(slug="gis-forum", name="GIS")
    thread = Thread(
        title="Retention ponds",
        slug="retention-ponds",
        body_html="<p>Experiences?</p>",
        body_text="Experiences?",
        author=author,
        category=category,
        tags=[nbs, gis],
    )
    db_session.add(thread)
    await db_session.flush()
    reply = await create_reply(db_session, thread_id=thread.id, author_id=author.id)
    ids = (thread.id, author.id, nbs.id, category.id, reply.id)
    db_session.expire_all()
    thread_id, author_id, nbs_id, category_id, reply_id = ids

    loaded = await db_session.get(Thread, thread_id)
    await db_session.refresh(loaded, ["author", "category", "tags", "replies"])
    assert loaded.author.id == author_id
    assert loaded.category.slug == "measures"
    assert [t.name for t in loaded.tags] == ["GIS", "NBS"]  # ordered by name
    assert [r.id for r in loaded.replies] == [reply_id]

    tag = await db_session.get(Tag, nbs_id)
    await db_session.refresh(tag, ["threads"])
    assert [t.id for t in tag.threads] == [thread_id]

    measures = await db_session.get(Category, category_id)
    await db_session.refresh(measures, ["threads"])
    assert thread_id in {t.id for t in measures.threads}

    loaded_reply = await db_session.get(Reply, reply_id)
    await db_session.refresh(loaded_reply, ["thread", "author"])
    assert loaded_reply.thread.id == thread_id
    assert loaded_reply.author.id == author_id


async def test_thread_tags_cascade_on_thread_and_tag_delete(db_session):
    tag_a = await create_tag(db_session)
    tag_b = await create_tag(db_session)
    thread = await _thread(db_session, tags=[tag_a, tag_b])
    await _thread(db_session, tags=[tag_b])

    async def links() -> int:
        return await db_session.scalar(
            text("SELECT count(*) FROM thread_tags WHERE tag_id IN (:a, :b)"),
            {"a": tag_a.id, "b": tag_b.id},
        )

    assert await links() == 3

    await db_session.execute(delete(Thread).where(Thread.id == thread.id))
    assert await links() == 1

    await db_session.execute(delete(Tag).where(Tag.id == tag_b.id))
    assert await links() == 0


async def test_category_delete_restricted_while_threads_exist(db_session):
    category = await create_category(db_session, kind=CategoryKind.FORUM)
    await _thread(db_session, category_id=category.id)

    await _expect_integrity_error(db_session, delete(Category).where(Category.id == category.id))


async def test_user_delete_sets_authors_and_approver_null(db_session):
    author = await create_user(db_session)
    admin = await create_user(db_session)
    thread = await _thread(
        db_session, author_id=author.id, approved_by=admin.id, approved_at=datetime.now(UTC)
    )
    reply = await create_reply(db_session, thread_id=thread.id, author_id=author.id)
    post = await _post(db_session)
    comment = await create_comment(db_session, post_id=post.id, author_id=author.id)

    await db_session.execute(delete(User).where(User.id.in_([author.id, admin.id])))

    row = (
        await db_session.execute(
            text("SELECT author_id, approved_by FROM threads WHERE id = :id"), {"id": thread.id}
        )
    ).one()
    assert row.author_id is None and row.approved_by is None
    assert (
        await db_session.scalar(
            text("SELECT author_id FROM replies WHERE id = :id"), {"id": reply.id}
        )
        is None
    )
    assert (
        await db_session.scalar(
            text("SELECT author_id FROM comments WHERE id = :id"), {"id": comment.id}
        )
        is None
    )


async def test_thread_indexes_exist(db_session):
    rows = (
        await db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'threads'")
        )
    ).all()
    defs = {name: definition for name, definition in rows}

    assert "USING gin (fts)" in defs["ix_threads_fts"]
    assert "gin_trgm_ops" in defs["ix_threads_title_trgm"]
    assert "(status, is_pinned DESC, last_activity_at DESC)" in defs["ix_threads_listing"]
    for name in ("ix_threads_category_id", "ix_threads_author_id", "ix_threads_locale"):
        assert name in defs


async def test_reply_and_comment_indexes_exist(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename IN ('replies', 'comments', 'thread_tags')"
            )
        )
    ).all()
    defs = {name: definition for name, definition in rows}

    assert "(thread_id, status, created_at)" in defs["ix_replies_thread_id_status_created_at"]
    assert "USING gin (fts)" in defs["ix_replies_fts"]
    assert "(post_id, status, created_at)" in defs["ix_comments_post_id_status_created_at"]
    for name in (
        "ix_replies_parent_reply_id",
        "ix_replies_author_id",
        "ix_comments_author_id",
        "ix_thread_tags_tag_id",
    ):
        assert name in defs


# --- replies: defaults, nesting ------------------------------------------------------------


async def test_reply_defaults_and_fts(db_session):
    thread = await _thread(db_session)
    reply = await create_reply(db_session, thread_id=thread.id, body="Swales absorb runoff.")
    await db_session.refresh(reply)

    assert isinstance(reply.id, int)
    assert reply.status is ContentStatus.PUBLISHED
    assert reply.parent_reply_id is None
    assert reply.report_count == 0 and reply.hidden_reason is None
    assert reply.deleted_at is None

    hit = await db_session.scalar(
        text("SELECT id FROM replies WHERE fts @@ plainto_tsquery('english', 'swale')")
    )
    assert hit == reply.id


async def test_reply_depth_one_allowed(db_session):
    thread = await _thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id)
    child = await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)
    sibling = await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)
    ids = (parent.id, child.id, sibling.id)
    db_session.expire_all()

    loaded_parent = await db_session.get(Reply, ids[0])
    await db_session.refresh(loaded_parent, ["children", "parent"])
    assert loaded_parent.parent is None
    assert [c.id for c in loaded_parent.children] == [ids[1], ids[2]]

    loaded_child = await db_session.get(Reply, ids[1])
    await db_session.refresh(loaded_child, ["parent"])
    assert loaded_child.parent.id == ids[0]


async def test_reply_depth_two_rejected(db_session):
    thread = await _thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id)
    child = await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)

    await _expect_nesting_error(
        db_session, _insert_reply_sql(), {"thread": thread.id, "parent": child.id}
    )


async def test_reply_parent_from_another_thread_rejected(db_session):
    thread = await _thread(db_session)
    other = await _thread(db_session)
    foreign_parent = await create_reply(db_session, thread_id=other.id)

    await _expect_nesting_error(
        db_session, _insert_reply_sql(), {"thread": thread.id, "parent": foreign_parent.id}
    )


async def test_reply_update_cannot_create_depth_two(db_session):
    thread = await _thread(db_session)
    top_a = await create_reply(db_session, thread_id=thread.id)
    top_b = await create_reply(db_session, thread_id=thread.id)
    child_of_a = await create_reply(db_session, thread_id=thread.id, parent_reply_id=top_a.id)

    # Re-parenting under a child would be depth 2.
    await _expect_nesting_error(
        db_session,
        update(Reply).where(Reply.id == top_b.id).values(parent_reply_id=child_of_a.id),
    )
    # A reply that has children cannot itself become a child (its children would be depth 2).
    await _expect_nesting_error(
        db_session,
        update(Reply).where(Reply.id == top_a.id).values(parent_reply_id=top_b.id),
    )
    # A reply cannot be its own parent.
    await _expect_nesting_error(
        db_session,
        update(Reply).where(Reply.id == top_b.id).values(parent_reply_id=top_b.id),
    )
    # Moving a child to another thread away from its parent is refused too.
    other = await _thread(db_session)
    await _expect_nesting_error(
        db_session,
        update(Reply).where(Reply.id == child_of_a.id).values(thread_id=other.id),
    )

    # A legal re-parent (childless top-level reply under another top-level reply) works.
    await db_session.execute(
        update(Reply).where(Reply.id == top_b.id).values(parent_reply_id=top_a.id)
    )


async def test_parent_reply_delete_keeps_children_with_null_parent(db_session):
    thread = await _thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id)
    child = await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)

    await db_session.execute(delete(Reply).where(Reply.id == parent.id))

    row = (
        await db_session.execute(
            text("SELECT parent_reply_id FROM replies WHERE id = :id"), {"id": child.id}
        )
    ).one_or_none()
    assert row is not None
    assert row.parent_reply_id is None


async def test_thread_delete_cascades_replies(db_session):
    thread = await _thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id)
    await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)
    keep = await _thread(db_session)
    kept = await create_reply(db_session, thread_id=keep.id)

    await db_session.execute(delete(Thread).where(Thread.id == thread.id))

    remaining = (
        await db_session.scalars(
            text("SELECT id FROM replies WHERE thread_id IN (:a, :b)"),
            {"a": thread.id, "b": keep.id},
        )
    ).all()
    assert remaining == [kept.id]
    assert await _reply_count(db_session, keep.id) == 1


async def test_orm_thread_delete_with_loaded_replies(db_session):
    thread = await _thread(db_session)
    parent = await create_reply(db_session, thread_id=thread.id)
    await create_reply(db_session, thread_id=thread.id, parent_reply_id=parent.id)
    await db_session.refresh(thread, ["replies"])
    assert len(thread.replies) == 2
    thread_id = thread.id

    await db_session.delete(thread)
    await db_session.flush()

    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM replies WHERE thread_id = :id"), {"id": thread_id}
        )
        == 0
    )


# --- counters ------------------------------------------------------------------------------


async def test_reply_count_counts_published_replies_only(db_session):
    thread = await _thread(db_session)

    await create_reply(db_session, thread_id=thread.id)
    assert await _reply_count(db_session, thread.id) == 1

    await create_reply(db_session, thread_id=thread.id, status=ContentStatus.PENDING)
    await create_reply(
        db_session,
        thread_id=thread.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )
    assert await _reply_count(db_session, thread.id) == 1

    await create_reply(db_session, thread_id=thread.id)
    assert await _reply_count(db_session, thread.id) == 2

    # The ORM sees the trigger's value after a refresh.
    await db_session.refresh(thread)
    assert thread.reply_count == 2


async def test_reply_count_follows_status_changes_and_deletes(db_session):
    thread = await _thread(db_session)
    first = await create_reply(db_session, thread_id=thread.id)
    second = await create_reply(db_session, thread_id=thread.id)
    pending = await create_reply(db_session, thread_id=thread.id, status=ContentStatus.PENDING)
    assert await _reply_count(db_session, thread.id) == 2

    first.status = ContentStatus.HIDDEN
    first.hidden_reason = HiddenReason.ADMIN
    await db_session.flush()
    assert await _reply_count(db_session, thread.id) == 1

    pending.status = ContentStatus.PUBLISHED
    await db_session.flush()
    assert await _reply_count(db_session, thread.id) == 2

    second.status = ContentStatus.DELETED
    await db_session.flush()
    assert await _reply_count(db_session, thread.id) == 1

    await db_session.execute(delete(Reply).where(Reply.id == pending.id))
    assert await _reply_count(db_session, thread.id) == 0

    first.status = ContentStatus.PUBLISHED
    await db_session.flush()
    assert await _reply_count(db_session, thread.id) == 1


async def test_reply_count_follows_a_reply_moved_to_another_thread(db_session):
    source = await _thread(db_session)
    target = await _thread(db_session)
    reply = await create_reply(db_session, thread_id=source.id)

    await db_session.execute(update(Reply).where(Reply.id == reply.id).values(thread_id=target.id))

    assert await _reply_count(db_session, source.id) == 0
    assert await _reply_count(db_session, target.id) == 1


async def test_last_activity_moves_on_published_reply_only(db_session):
    thread = await _thread(db_session, last_activity_at=OLD)

    await create_reply(db_session, thread_id=thread.id, status=ContentStatus.PENDING)
    await db_session.refresh(thread)
    assert thread.last_activity_at == OLD

    await create_reply(db_session, thread_id=thread.id)
    await db_session.refresh(thread)
    assert thread.last_activity_at > OLD
    now = await db_session.scalar(text("SELECT now()"))
    assert thread.last_activity_at == now


async def test_comment_count_counts_published_comments_only(db_session):
    post = await _post(db_session)
    assert post.comment_count == 0

    first = await create_comment(db_session, post_id=post.id)
    await create_comment(db_session, post_id=post.id, status=ContentStatus.PENDING)
    second = await create_comment(db_session, post_id=post.id)
    assert await _comment_count(db_session, post.id) == 2

    first.status = ContentStatus.HIDDEN
    first.hidden_reason = HiddenReason.AUTO_REPORTS
    await db_session.flush()
    assert await _comment_count(db_session, post.id) == 1

    await db_session.execute(delete(Comment).where(Comment.id == second.id))
    assert await _comment_count(db_session, post.id) == 0

    first.status = ContentStatus.PUBLISHED
    await db_session.flush()
    assert await _comment_count(db_session, post.id) == 1

    await db_session.refresh(post)
    assert post.comment_count == 1


# --- comments ------------------------------------------------------------------------------


async def test_comment_defaults_and_relationships(db_session):
    author = await create_user(db_session)
    post = await _post(db_session)
    comment = await create_comment(db_session, post_id=post.id, author_id=author.id)
    ids = (post.id, author.id, comment.id)
    db_session.expire_all()
    post_id, author_id, comment_id = ids

    loaded = await db_session.get(Comment, comment_id)
    await db_session.refresh(loaded, ["post", "author"])
    assert isinstance(loaded.id, int)
    assert loaded.status is ContentStatus.PUBLISHED
    assert loaded.report_count == 0 and loaded.deleted_at is None
    assert loaded.post.id == post_id
    assert loaded.author.id == author_id

    loaded_post = await db_session.get(Post, post_id)
    await db_session.refresh(loaded_post, ["comments"])
    assert [c.id for c in loaded_post.comments] == [comment_id]


async def test_post_delete_cascades_comments(db_session):
    post = await _post(db_session)
    await create_comment(db_session, post_id=post.id)
    await create_comment(db_session, post_id=post.id)
    post_id = post.id

    await db_session.execute(delete(Post).where(Post.id == post_id))

    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM comments WHERE post_id = :id"), {"id": post_id}
        )
        == 0
    )


# --- enums, triggers, autogenerate ---------------------------------------------------------


async def test_forum_tables_reuse_existing_enum_types(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT table_name, column_name, udt_name FROM information_schema.columns "
                "WHERE table_name IN ('threads', 'replies', 'comments') "
                "AND column_name IN ('status', 'hidden_reason')"
            )
        )
    ).all()
    assert len(rows) == 6
    assert {(r.column_name, r.udt_name) for r in rows} == {
        ("status", "content_status"),
        ("hidden_reason", "hidden_reason"),
    }
    # No new enum types were introduced by 0005.
    types = set(
        (
            await db_session.scalars(
                text("SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY typname")
            )
        ).all()
    )
    assert types == {
        "category_kind",
        "content_status",
        "content_type",
        "digest_frequency",
        "hidden_reason",
        "kb_type",
        "organisation_type",
        "token_purpose",
        "user_role",
    }


FORUM_TRIGGERS = {
    ("replies", "replies_one_level"),
    ("replies", "replies_reply_count"),
    ("comments", "comments_comment_count"),
}
FORUM_FUNCTIONS = {"replies_one_level", "replies_reply_count", "comments_comment_count"}

TRIGGERS_SQL = text(
    "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "WHERE NOT t.tgisinternal"
)
FUNCTIONS_SQL = text(
    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'public' AND p.prorettype = 'trigger'::regtype"
)


async def test_forum_triggers_installed(db_session):
    triggers = {tuple(r) for r in (await db_session.execute(TRIGGERS_SQL)).all()}
    functions = set((await db_session.scalars(FUNCTIONS_SQL)).all())

    assert FORUM_TRIGGERS <= triggers
    assert FORUM_FUNCTIONS <= functions


async def test_autogenerate_is_clean_and_quiet(db_session):
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


@pytest.fixture
async def empty_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine bound to a brand-new empty database, dropped after the test."""
    name = f"forum_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))

    engine = create_async_engine(make_url(database_url).set(database=name), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_downgrade_0005_drops_tables_triggers_and_functions(empty_engine):
    from alembic import command

    from app.db.migrations import alembic_config

    def upgrade(sync_conn, revision: str = "head"):
        command.upgrade(alembic_config(sync_conn), revision)

    def downgrade(sync_conn):
        command.downgrade(alembic_config(sync_conn), "0004")

    async with empty_engine.begin() as conn:
        await conn.run_sync(upgrade)
    async with empty_engine.begin() as conn:
        await conn.run_sync(downgrade)

    async with empty_engine.connect() as conn:
        tables = set(
            (
                await conn.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).all()
        )
        triggers = {tuple(r) for r in (await conn.execute(TRIGGERS_SQL)).all()}
        functions = set((await conn.scalars(FUNCTIONS_SQL)).all())
    assert not {"threads", "thread_tags", "replies", "comments"} & tables
    assert "posts" in tables
    assert not FORUM_TRIGGERS & triggers
    assert not FORUM_FUNCTIONS & functions

    async with empty_engine.begin() as conn:
        await conn.run_sync(upgrade)
    async with empty_engine.connect() as conn:
        assert FORUM_FUNCTIONS <= set((await conn.scalars(FUNCTIONS_SQL)).all())
