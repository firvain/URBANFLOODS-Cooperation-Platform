"""Alembic migrations: apply cleanly to an empty database, round-trip, stay linear and in sync.

Each test that runs migrations gets its own freshly created, empty database, so the session
database (migrated once by ``conftest.py``) is never disturbed. Alembic is driven through
``AsyncConnection.run_sync`` with the connection shared via ``Config.attributes`` (Alembic
cookbook, "Programmatic API use (connection sharing) With Asyncio"), so ``env.py`` never calls
``asyncio.run`` inside pytest's running event loop.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REQUIRED_EXTENSIONS = {"pg_trgm", "citext"}


def _head_revision() -> str:
    from alembic.script import ScriptDirectory

    from app.db.migrations import alembic_config

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None
    return head


async def _version(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
        return [row[0] for row in rows]


async def _extensions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT extname FROM pg_extension"))
        return {row[0] for row in rows}


async def _upgrade(engine: AsyncEngine) -> None:
    from app.db.migrations import upgrade_head

    async with engine.begin() as conn:
        await conn.run_sync(upgrade_head)


async def _downgrade(engine: AsyncEngine) -> None:
    from app.db.migrations import downgrade_base

    async with engine.begin() as conn:
        await conn.run_sync(downgrade_base)


@pytest.fixture
async def empty_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine bound to a brand-new empty database, dropped after the test."""
    name = f"migrations_{uuid.uuid4().hex[:12]}"
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


async def test_upgrade_head_on_empty_database(empty_engine):
    async with empty_engine.connect() as conn:
        tables = await conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        )
        assert tables.scalar_one() == 0

    await _upgrade(empty_engine)

    assert await _version(empty_engine) == [_head_revision()]


async def test_extensions_installed_after_upgrade(empty_engine):
    await _upgrade(empty_engine)

    assert REQUIRED_EXTENSIONS <= await _extensions(empty_engine)


async def test_downgrade_base_then_upgrade_again(empty_engine):
    await _upgrade(empty_engine)

    await _downgrade(empty_engine)
    assert await _version(empty_engine) == []
    assert not REQUIRED_EXTENSIONS & await _extensions(empty_engine)

    await _upgrade(empty_engine)
    assert await _version(empty_engine) == [_head_revision()]
    assert REQUIRED_EXTENSIONS <= await _extensions(empty_engine)


def test_migration_history_is_linear():
    from alembic.script import ScriptDirectory

    from app.db.migrations import alembic_config

    script = ScriptDirectory.from_config(alembic_config())
    revisions = list(script.walk_revisions())

    assert len(script.get_heads()) == 1
    assert len(script.get_bases()) == 1
    assert revisions, "expected at least one migration"
    assert not [rev.revision for rev in revisions if rev.is_branch_point]
    assert not [rev.revision for rev in revisions if rev.is_merge_point]


async def test_session_database_is_migrated_to_head(db_session):
    """conftest.py upgrades the session database to head once, before any test runs."""
    result = await db_session.execute(text("SELECT version_num FROM alembic_version"))

    assert [row[0] for row in result] == [_head_revision()]


async def test_autogenerate_produces_no_diff(empty_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from app.db.models import Base

    await _upgrade(empty_engine)

    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with empty_engine.connect() as conn:
        assert await conn.run_sync(diff) == []


MEMBER_NOTIFICATION_COLUMNS = (
    "reply_to_my_thread",
    "comment_on_my_post",
    "reply_to_my_reply",
    "moderation_decisions",
)


async def _preference_defaults(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' AND column_default IS NOT NULL"
            )
        )
        return {row.column_name: row.column_default for row in rows}


async def test_0009_switches_member_notification_defaults_off_and_keeps_rows(empty_engine):
    """0009: new rows get the four member notifications off; existing rows keep their values;
    the admin digest stays on; downgrade restores the old defaults."""
    from alembic import command

    from app.db.migrations import alembic_config

    def to(revision: str, *, down: bool = False):
        def run(sync_conn):
            step = command.downgrade if down else command.upgrade
            step(alembic_config(sync_conn), revision)

        return run

    insert_user = text(
        "INSERT INTO users (email, password_hash, display_name) "
        "VALUES (:email, 'x', 'Member') RETURNING id"
    )
    select_prefs = text(
        "SELECT reply_to_my_thread, comment_on_my_post, reply_to_my_reply, "
        "moderation_decisions, admin_digest FROM notification_preferences WHERE user_id = :id"
    )

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0008"))
        old_id = (await conn.execute(insert_user, {"email": "old@example.org"})).scalar_one()
        await conn.execute(
            text("INSERT INTO notification_preferences (user_id) VALUES (:id)"), {"id": old_id}
        )

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0009"))
        new_id = (await conn.execute(insert_user, {"email": "new@example.org"})).scalar_one()
        await conn.execute(
            text("INSERT INTO notification_preferences (user_id) VALUES (:id)"), {"id": new_id}
        )
        old = (await conn.execute(select_prefs, {"id": old_id})).one()
        new = (await conn.execute(select_prefs, {"id": new_id})).one()

    assert tuple(old) == (True, True, True, True, True)  # existing member keeps everything
    assert tuple(new) == (False, False, False, False, True)  # admin_digest stays on
    defaults = await _preference_defaults(empty_engine)
    assert all(defaults[column] == "false" for column in MEMBER_NOTIFICATION_COLUMNS)
    assert defaults["admin_digest"] == "true"
    assert defaults["digest_frequency"].startswith("'daily'")

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0008", down=True))
    defaults = await _preference_defaults(empty_engine)
    assert all(defaults[column] == "true" for column in MEMBER_NOTIFICATION_COLUMNS)


async def _columns(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": table},
        )
        return {row[0] for row in rows}


async def test_0011_backfills_rejected_at_from_the_audit_log(empty_engine):
    """0011: ``rejected_at`` on posts and threads is the latest ``moderation.reject`` audit row
    for that very item, when it is later than the item's approval (or it was never approved);
    other actions and the other content type's rows with the same id do not count. Downgrade
    drops the column again."""
    from alembic import command

    from app.db.migrations import alembic_config

    def to(revision: str, *, down: bool = False):
        def run(sync_conn):
            step = command.downgrade if down else command.upgrade
            step(alembic_config(sync_conn), revision)

        return run

    t1 = datetime(2026, 10, 1, 10, tzinfo=UTC)
    t2 = datetime(2026, 10, 2, 10, tzinfo=UTC)
    t3 = datetime(2026, 10, 3, 10, tzinfo=UTC)
    # name -> (status, approved_at, [(action, created_at)])
    cases: dict[str, tuple[str, datetime | None, list[tuple[str, datetime]]]] = {
        "rejected_once": ("hidden", None, [("moderation.reject", t1)]),
        "rejected_twice_resubmitted": (
            "pending",
            None,
            [("moderation.reject", t1), ("moderation.resubmit", t2), ("moderation.reject", t3)],
        ),
        "rejected_then_approved": ("published", t2, [("moderation.reject", t1)]),
        "approved_then_rejected": ("hidden", t1, [("moderation.reject", t2)]),
        "never_rejected": ("pending", None, [("moderation.hide", t1)]),
    }

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0010"))
        categories = {}
        for kind in ("blog", "forum"):
            categories[kind] = (
                await conn.execute(
                    text(
                        "INSERT INTO categories (kind, slug, name) "
                        "VALUES (CAST(:kind AS category_kind), :kind, :kind) RETURNING id"
                    ),
                    {"kind": kind},
                )
            ).scalar_one()
        ids: dict[tuple[str, str], int] = {}
        # Posts get ids 1.., threads 101..: no post shares an id with a thread.
        tables = (("posts", "post", "blog", 1), ("threads", "thread", "forum", 101))
        for table, target_type, kind, first_id in tables:
            for offset, (name, (status, approved_at, audits)) in enumerate(cases.items()):
                content_id = (
                    await conn.execute(
                        text(
                            f"INSERT INTO {table} (id, category_id, title, slug, body_html, "
                            "body_text, status, approved_at) VALUES (:id, :cat, :name, :slug, "
                            "'<p>x</p>', 'x', CAST(:status AS content_status), "
                            "CAST(:approved_at AS timestamptz)) RETURNING id"
                        ),
                        {
                            "id": first_id + offset,
                            "cat": categories[kind],
                            "name": name,
                            "slug": f"{target_type}-{name}".replace("_", "-"),
                            "status": status,
                            "approved_at": approved_at,
                        },
                    )
                ).scalar_one()
                ids[(table, name)] = content_id
                for action, created_at in audits:
                    await conn.execute(
                        text(
                            "INSERT INTO audit_log (action, target_type, target_id, created_at) "
                            "VALUES (:action, :tt, :id, CAST(:at AS timestamptz))"
                        ),
                        {"action": action, "tt": target_type, "id": content_id, "at": created_at},
                    )
        # A reject logged for the other content type under the never-rejected item's id (no item
        # of that type has it) must not leak across tables: only the target type tells them apart.
        for table, other_type in (("posts", "thread"), ("threads", "post")):
            await conn.execute(
                text(
                    "INSERT INTO audit_log (action, target_type, target_id, created_at) "
                    "VALUES ('moderation.reject', :tt, :id, CAST(:at AS timestamptz))"
                ),
                {"tt": other_type, "id": ids[(table, "never_rejected")], "at": t3},
            )

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0011"))
        result: dict[tuple[str, str], str | None] = {}
        for (table, name), content_id in ids.items():
            value = (
                await conn.execute(
                    text(
                        f"SELECT to_char(rejected_at AT TIME ZONE 'UTC', "
                        f"'YYYY-MM-DD\"T\"HH24:MI:SS') FROM {table} WHERE id = :id"
                    ),
                    {"id": content_id},
                )
            ).scalar_one()
            result[(table, name)] = value

    for table in ("posts", "threads"):
        assert result[(table, "rejected_once")] == "2026-10-01T10:00:00"
        assert result[(table, "rejected_twice_resubmitted")] == "2026-10-03T10:00:00"
        assert result[(table, "rejected_then_approved")] is None
        assert result[(table, "approved_then_rejected")] == "2026-10-02T10:00:00"
        assert result[(table, "never_rejected")] is None

    async with empty_engine.begin() as conn:
        await conn.run_sync(to("0010", down=True))
    assert "rejected_at" not in await _columns(empty_engine, "posts")
    assert "rejected_at" not in await _columns(empty_engine, "threads")
