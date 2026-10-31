"""Increment 4a: moderation schema (``reports``, ``digest_runs``) and the ``report_reason`` /
``report_status`` enums (migration 0006).

Like ``test_models_forum.py``: every test runs inside the ``db_session`` transaction and only
flushes, so the fixture's rollback leaves no rows behind. Statements expected to fail run inside
a SAVEPOINT so the transaction stays usable.
"""

from __future__ import annotations

import uuid
import warnings
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.enums import ContentType, ReportReason, ReportStatus
from app.db.models import DigestRun, Report, User
from tests.factories import create_report, create_user

ENUM_VALUES_SQL = text(
    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
    "WHERE t.typname = :name ORDER BY e.enumsortorder"
)
INDEXES_SQL = text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :table")
MODERATION_TABLES = {"reports", "digest_runs"}
MODERATION_ENUMS = {"report_reason", "report_status"}


async def _insert_report(db, *, reporter_id, content_type="post", content_id=1) -> None:
    async with db.begin_nested():
        await db.execute(
            text(
                "INSERT INTO reports (reporter_id, content_type, content_id, reason) "
                "VALUES (:r, CAST(:t AS content_type), :c, 'spam')"
            ),
            {"r": reporter_id, "t": content_type, "c": content_id},
        )


# --- enums ---------------------------------------------------------------------------------


def test_python_enum_values():
    assert [m.value for m in ReportReason] == [
        "spam",
        "abuse",
        "off_topic",
        "misinformation",
        "other",
    ]
    assert [m.value for m in ReportStatus] == ["open", "resolved", "dismissed"]


async def test_pg_enum_values_match_python(db_session):
    for name, enum_cls in (("report_reason", ReportReason), ("report_status", ReportStatus)):
        labels = (await db_session.scalars(ENUM_VALUES_SQL, {"name": name})).all()
        assert labels == [m.value for m in enum_cls]


# --- reports -------------------------------------------------------------------------------


async def test_report_defaults(db_session):
    reporter = await create_user(db_session)
    report = await create_report(
        db_session, reporter_id=reporter.id, content_type=ContentType.THREAD, content_id=42
    )
    await db_session.refresh(report)

    assert report.id is not None
    assert report.status is ReportStatus.OPEN
    assert report.reason is ReportReason.SPAM
    assert report.content_type is ContentType.THREAD
    assert report.content_id == 42
    assert report.details is None
    assert report.resolved_by is None and report.resolved_at is None
    assert report.created_at is not None


async def test_report_stores_reason_details_and_enum_values(db_session):
    reporter = await create_user(db_session)
    report = await create_report(
        db_session,
        reporter_id=reporter.id,
        content_type=ContentType.COMMENT,
        content_id=7,
        reason=ReportReason.OFF_TOPIC,
        details="Not about flooding.",
    )

    row = (
        await db_session.execute(
            text(
                "SELECT content_type::text, reason::text, status::text, details "
                "FROM reports WHERE id = :id"
            ),
            {"id": report.id},
        )
    ).one()
    assert tuple(row) == ("comment", "off_topic", "open", "Not about flooding.")


async def test_report_details_max_length(db_session):
    reporter = await create_user(db_session)
    with pytest.raises(DBAPIError, match="too long"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO reports (reporter_id, content_type, content_id, reason, details) "
                    "VALUES (:r, 'post', 1, 'other', :d)"
                ),
                {"r": reporter.id, "d": "x" * 1001},
            )


async def test_report_unique_per_reporter_and_item(db_session):
    reporter = await create_user(db_session)
    other = await create_user(db_session)
    await _insert_report(db_session, reporter_id=reporter.id, content_id=100)

    with pytest.raises(IntegrityError) as info:
        await _insert_report(db_session, reporter_id=reporter.id, content_id=100)
    assert "uq_reports_reporter_content" in str(info.value)

    # A different item (id or type) or a different reporter is fine.
    await _insert_report(db_session, reporter_id=reporter.id, content_id=101)
    await _insert_report(db_session, reporter_id=reporter.id, content_type="thread", content_id=100)
    await _insert_report(db_session, reporter_id=other.id, content_id=100)

    count = await db_session.scalar(
        text("SELECT count(*) FROM reports WHERE reporter_id IN (:a, :b)"),
        {"a": reporter.id, "b": other.id},
    )
    assert count == 4


async def test_report_null_reporters_do_not_collide(db_session):
    """Anonymised (NULL) reporters never block each other: Postgres NULLs are distinct."""
    await _insert_report(db_session, reporter_id=None, content_id=200)
    await _insert_report(db_session, reporter_id=None, content_id=200)

    count = await db_session.scalar(
        text("SELECT count(*) FROM reports WHERE content_id = 200 AND reporter_id IS NULL")
    )
    assert count == 2


async def test_report_reporter_and_resolver_set_null_on_user_delete(db_session):
    reporter = await create_user(db_session)
    admin = await create_user(db_session)
    report = await create_report(
        db_session,
        reporter_id=reporter.id,
        content_id=300,
        status=ReportStatus.RESOLVED,
        resolved_by=admin.id,
        resolved_at=datetime.now(UTC),
    )

    await db_session.execute(delete(User).where(User.id.in_([reporter.id, admin.id])))

    row = (
        await db_session.execute(
            text("SELECT reporter_id, resolved_by, status::text FROM reports WHERE id = :id"),
            {"id": report.id},
        )
    ).one()
    assert row.reporter_id is None
    assert row.resolved_by is None
    assert row.status == "resolved"


async def test_report_relationships(db_session):
    reporter = await create_user(db_session)
    admin = await create_user(db_session)
    report = await create_report(
        db_session, reporter_id=reporter.id, content_id=400, resolved_by=admin.id
    )
    ids = (report.id, reporter.id, admin.id)
    db_session.expire_all()
    report_id, reporter_id, admin_id = ids

    loaded = await db_session.get(Report, report_id)
    await db_session.refresh(loaded, ["reporter", "resolver"])
    assert loaded.reporter.id == reporter_id
    assert loaded.resolver.id == admin_id


async def test_report_indexes(db_session):
    indexes = dict((await db_session.execute(INDEXES_SQL, {"table": "reports"})).all())

    assert "(status, created_at)" in indexes["ix_reports_status_created_at"]
    assert "(content_type, content_id)" in indexes["ix_reports_content_type_content_id"]
    assert "UNIQUE" in indexes["uq_reports_reporter_content"]
    assert "(reporter_id, content_type, content_id)" in indexes["uq_reports_reporter_content"]


# --- digest_runs ---------------------------------------------------------------------------


async def test_digest_run_insert_and_defaults(db_session):
    end = datetime.now(UTC)
    run = DigestRun(kind="admin_daily", window_start=end - timedelta(days=1), window_end=end)
    db_session.add(run)
    await db_session.flush()
    await db_session.refresh(run)

    assert run.id is not None
    assert run.ran_at is not None
    assert run.recipients == 0
    assert run.items == 0
    assert run.window_end - run.window_start == timedelta(days=1)


async def test_digest_run_latest_by_kind(db_session):
    base = datetime(2030, 1, 1, tzinfo=UTC)
    kind = f"test_{uuid.uuid4().hex[:8]}"
    for days in (0, 2, 1):
        db_session.add(
            DigestRun(
                kind=kind,
                ran_at=base + timedelta(days=days),
                window_start=base,
                window_end=base + timedelta(days=days),
                recipients=days,
            )
        )
    await db_session.flush()

    latest = await db_session.scalar(
        select(DigestRun).where(DigestRun.kind == kind).order_by(DigestRun.ran_at.desc()).limit(1)
    )
    assert latest.recipients == 2


async def test_digest_runs_ordering_index(db_session):
    indexes = dict((await db_session.execute(INDEXES_SQL, {"table": "digest_runs"})).all())

    assert "(kind, ran_at DESC)" in indexes["ix_digest_runs_kind_ran_at"]


# --- migration -----------------------------------------------------------------------------


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
    name = f"moderation_{uuid.uuid4().hex[:12]}"
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


async def _tables_and_types(engine: AsyncEngine) -> tuple[set[str], set[str]]:
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).all()
        )
        types = set((await conn.scalars(text("SELECT typname FROM pg_type"))).all())
    return tables, types


async def test_downgrade_0006_drops_tables_and_enum_types(empty_engine):
    from alembic import command

    from app.db.migrations import alembic_config

    def upgrade(sync_conn):
        command.upgrade(alembic_config(sync_conn), "0006")

    def downgrade(sync_conn):
        command.downgrade(alembic_config(sync_conn), "0005")

    async with empty_engine.begin() as conn:
        await conn.run_sync(upgrade)
    tables, types = await _tables_and_types(empty_engine)
    assert MODERATION_TABLES <= tables
    assert MODERATION_ENUMS <= types

    async with empty_engine.begin() as conn:
        await conn.run_sync(downgrade)
    tables, types = await _tables_and_types(empty_engine)
    assert not MODERATION_TABLES & tables
    assert not MODERATION_ENUMS & types
    # The shared content_type enum belongs to 0004 and survives.
    assert {"content_type", "content_status"} <= types
    assert {"threads", "posts"} <= tables

    async with empty_engine.begin() as conn:
        await conn.run_sync(upgrade)
    tables, types = await _tables_and_types(empty_engine)
    assert MODERATION_TABLES <= tables
    assert MODERATION_ENUMS <= types
