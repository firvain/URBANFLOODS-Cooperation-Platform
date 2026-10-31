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
