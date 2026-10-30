"""Shared test fixtures.

Database: one Postgres for the whole session. If ``TEST_DATABASE_URL`` is set it is used as-is
(e.g. ``docker-compose.test.yml`` on port 5434); otherwise a ``postgres:16-alpine`` container is
started with testcontainers. If neither is available, DB-backed tests are skipped with a reason.

The database is resolved in ``pytest_configure`` because the app builds its settings and its
async engine at import time, and test modules import ``app`` during collection.

Schema: when a database is available it is migrated to Alembic head once per session (autouse
fixture below), before any test runs. ``db_session`` rolls back after every test.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

# Test environment, set before anything under ``app`` is imported.
os.environ.update(
    {
        "ENV": "test",
        "ENABLE_DOCS": "true",
        "EMAIL_ENABLED": "false",
        "TURNSTILE_ENABLED": "false",
        "RATE_LIMIT_ENABLED": "false",
        "ENABLE_SCHEDULER": "false",
        "SECRET_KEY": "test-secret",
        "ALLOWED_ORIGINS": "http://localhost:5173",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
    }
)

# Used only when no database is available; nothing listens on port 1.
_UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"

_postgres_container = None
_database_url: str | None = None
_database_unavailable_reason: str | None = None


def _to_asyncpg_url(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def pytest_configure(config: pytest.Config) -> None:
    global _postgres_container, _database_url, _database_unavailable_reason

    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        _database_url = _to_asyncpg_url(explicit)
    else:
        try:
            from testcontainers.community.postgres import PostgresContainer

            container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
            container.start()
        except Exception as exc:  # Docker not running, image pull failed, ...
            _database_unavailable_reason = (
                f"No test database: TEST_DATABASE_URL is unset and testcontainers could not "
                f"start postgres:16-alpine ({type(exc).__name__}: {exc})"
            )
        else:
            _postgres_container = container
            _database_url = container.get_connection_url()

    os.environ["DATABASE_URL"] = _database_url or _UNREACHABLE_DATABASE_URL


def pytest_unconfigure(config: pytest.Config) -> None:
    if _postgres_container is not None:
        _postgres_container.stop()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of the test database; skips the requesting test if there is none."""
    if _database_url is None:
        pytest.skip(_database_unavailable_reason or "No test database available")
    return _database_url


@pytest.fixture(scope="session", autouse=True)
async def _migrate_test_database() -> None:
    """Upgrade the session database to head once. No-op when there is no database.

    Runs inside pytest-asyncio's session event loop, so Alembic gets a connection through
    ``run_sync`` (``env.py`` then skips its own ``asyncio.run``).
    """
    if _database_url is None:
        return

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.migrations import upgrade_head

    engine = create_async_engine(_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_head)
    finally:
        await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    import httpx
    from asgi_lifespan import LifespanManager

    # Imported lazily so DATABASE_URL is already set (see pytest_configure).
    from app.main import app

    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def db_session(database_url: str) -> AsyncIterator[AsyncSession]:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
async def outbox() -> AsyncIterator[list]:
    """The in-memory email outbox (``list[OutgoingEmail]``), empty at the start of each test.

    Needs no database. In the test env ``get_backend()`` is always an ``OutboxBackend``.
    """
    from app.services.email import OutboxBackend, get_backend, reset_backend

    reset_backend()
    backend = get_backend()
    assert isinstance(backend, OutboxBackend)
    try:
        yield backend.messages
    finally:
        backend.messages.clear()
        reset_backend()


@pytest.fixture
async def cleanup_users(database_url: str) -> AsyncIterator[set[str]]:
    """Emails of users the test commits (directly or through the API); deleted afterwards.

    ``db_session`` rollback cannot undo rows the app committed, so endpoint tests add every
    address they create here. Sessions, email tokens and notification preferences go with the
    user (``ON DELETE CASCADE``); audit rows about or by the user are deleted explicitly.
    """
    from sqlalchemy import delete, or_, select

    from app.db.models import AuditLog, User
    from app.db.session import AsyncSessionLocal

    emails: set[str] = set()
    yield emails
    if not emails:
        return
    async with AsyncSessionLocal() as session, session.begin():
        ids = list((await session.scalars(select(User.id).where(User.email.in_(emails)))).all())
        if ids:
            await session.execute(
                delete(AuditLog).where(
                    or_(
                        AuditLog.actor_id.in_(ids),
                        (AuditLog.target_type == "user") & AuditLog.target_id.in_(ids),
                    )
                )
            )
            await session.execute(delete(User).where(User.id.in_(ids)))


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> Iterator[None]:
    """Leave structlog configured as the test found it.

    The app lifespan (``client`` fixture) calls ``configure_logging``, which installs a
    level-filtering wrapper (WARNING in tests); without this, any later test using
    ``structlog.testing.capture_logs`` for INFO events would depend on test order.
    """
    import structlog

    saved = structlog.get_config()
    yield
    structlog.configure(**saved)
