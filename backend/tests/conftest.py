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
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import httpx
    import respx
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

# Sent by the SPA on every request (``services/api.ts``); the CSRF middleware requires it on
# cookie-authenticated unsafe requests. Test clients send it by default, like the frontend.
CLIENT_DEFAULT_HEADERS = {"X-Requested-With": "XMLHttpRequest"}

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
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=CLIENT_DEFAULT_HEADERS
        ) as ac:
            yield ac


@pytest.fixture
async def other_client(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """A second client (own cookie jar) on the same running app: a second "device".

    Depends on ``client`` so the app's lifespan is already running.
    """
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=CLIENT_DEFAULT_HEADERS
    ) as ac:
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


@pytest.fixture
async def cleanup_organisations(database_url: str) -> AsyncIterator[set[str]]:
    """Names of organisations the test commits (directly or through the API); deleted
    afterwards together with the audit rows about them. Users pointing at them get
    ``organisation_id = NULL`` (``ON DELETE SET NULL``)."""
    from sqlalchemy import delete, select

    from app.db.models import AuditLog, Organisation
    from app.db.session import AsyncSessionLocal

    names: set[str] = set()
    yield names
    if not names:
        return
    async with AsyncSessionLocal() as session, session.begin():
        ids = list(
            (await session.scalars(select(Organisation.id).where(Organisation.name.in_(names))))
        )
        if ids:
            await session.execute(
                delete(AuditLog).where(
                    (AuditLog.target_type == "organisation") & AuditLog.target_id.in_(ids)
                )
            )
            await session.execute(delete(Organisation).where(Organisation.id.in_(ids)))


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


@pytest.fixture
async def cleanup_user_ids(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of users the test commits whose email changes under it, deleted afterwards.

    An anonymised (``DELETE /auth/me``) account's email becomes ``deleted-<id>@invalid``, so
    ``cleanup_users`` (which matches by email) no longer finds it. Only rows that are still
    anonymised (``email LIKE 'deleted-%@invalid'``) are removed, together with the audit rows by
    or about them; anything else stays for ``cleanup_users``.
    """
    from sqlalchemy import delete, or_, select

    from app.db.models import AuditLog, User
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        deleted = list(
            (
                await session.scalars(
                    select(User.id).where(User.id.in_(ids), User.email.like("deleted-%@invalid"))
                )
            ).all()
        )
        if deleted:
            await session.execute(
                delete(AuditLog).where(
                    or_(
                        AuditLog.actor_id.in_(deleted),
                        (AuditLog.target_type == "user") & AuditLog.target_id.in_(deleted),
                    )
                )
            )
            await session.execute(delete(User).where(User.id.in_(deleted)))


@pytest.fixture
async def cleanup_posts(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of posts the test commits; deleted afterwards (``post_tags`` rows cascade)."""
    from sqlalchemy import delete

    from app.db.models import Post
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Post).where(Post.id.in_(ids)))


@pytest.fixture
async def cleanup_categories(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of categories the test commits (directly or through the API); deleted afterwards
    together with any posts in them (``ON DELETE RESTRICT`` would refuse otherwise) and the
    audit rows about them."""
    from sqlalchemy import delete

    from app.db.models import AuditLog, Category, Post
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Post).where(Post.category_id.in_(ids)))
        await session.execute(
            delete(AuditLog).where(
                (AuditLog.target_type == "category") & AuditLog.target_id.in_(ids)
            )
        )
        await session.execute(delete(Category).where(Category.id.in_(ids)))


@pytest.fixture
async def cleanup_tags(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of tags the test commits; deleted afterwards (``post_tags`` rows cascade) together
    with the audit rows about them. Ids already gone (deleted or merged away) are fine."""
    from sqlalchemy import delete

    from app.db.models import AuditLog, Tag
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            delete(AuditLog).where((AuditLog.target_type == "tag") & AuditLog.target_id.in_(ids))
        )
        await session.execute(delete(Tag).where(Tag.id.in_(ids)))


@pytest.fixture(scope="session", autouse=True)
def upload_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """``settings.UPLOAD_DIR`` points at a temporary directory for the whole session, so no
    test writes under ``backend/uploads``. The app reads the setting per request."""
    from app.core.config import settings

    path = tmp_path_factory.mktemp("uploads")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "UPLOAD_DIR", str(path))
        yield path


@pytest.fixture
async def cleanup_knowbase_links(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of posts whose ``knowbase_links`` rows the test commits; those rows are deleted
    afterwards (the table is polymorphic, so nothing cascades from ``posts``)."""
    from sqlalchemy import delete

    from app.db.enums import ContentType
    from app.db.models import KnowbaseLink
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            delete(KnowbaseLink).where(
                KnowbaseLink.content_type == ContentType.POST,
                KnowbaseLink.content_id.in_(ids),
            )
        )


@pytest.fixture
async def cleanup_threads(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of threads the test commits; deleted afterwards (``replies`` and ``thread_tags`` rows
    cascade) together with their ``knowbase_links`` rows and the audit rows about them.

    Request it after ``cleanup_categories`` when both are used, so it tears down first (a
    category with threads cannot be deleted)."""
    from sqlalchemy import delete

    from app.db.enums import ContentType
    from app.db.models import AuditLog, KnowbaseLink, Thread
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            delete(KnowbaseLink).where(
                KnowbaseLink.content_type == ContentType.THREAD,
                KnowbaseLink.content_id.in_(ids),
            )
        )
        await session.execute(
            delete(AuditLog).where((AuditLog.target_type == "thread") & AuditLog.target_id.in_(ids))
        )
        await session.execute(delete(Thread).where(Thread.id.in_(ids)))


@pytest.fixture
async def cleanup_comments(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of comments the test commits on posts that outlive the test; deleted afterwards
    (comments on posts registered with ``cleanup_posts`` cascade anyway)."""
    from sqlalchemy import delete

    from app.db.models import Comment
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Comment).where(Comment.id.in_(ids)))


@pytest.fixture
async def cleanup_forum_categories(cleanup_categories: set[int]) -> AsyncIterator[set[int]]:
    """``cleanup_categories`` for forum tests: the same set of category ids, but every thread in
    those categories (with its ``knowbase_links`` rows and the audit rows about it) is deleted
    first, so threads created through the API need no separate registration. Replies and
    ``thread_tags`` rows cascade. Tears down before ``cleanup_categories`` (it depends on it)."""
    from sqlalchemy import delete, select

    from app.db.enums import ContentType
    from app.db.models import AuditLog, KnowbaseLink, Thread
    from app.db.session import AsyncSessionLocal

    yield cleanup_categories
    if not cleanup_categories:
        return
    async with AsyncSessionLocal() as session, session.begin():
        ids = list(
            (
                await session.scalars(
                    select(Thread.id).where(Thread.category_id.in_(cleanup_categories))
                )
            ).all()
        )
        if not ids:
            return
        await session.execute(
            delete(KnowbaseLink).where(
                KnowbaseLink.content_type == ContentType.THREAD,
                KnowbaseLink.content_id.in_(ids),
            )
        )
        await session.execute(
            delete(AuditLog).where((AuditLog.target_type == "thread") & AuditLog.target_id.in_(ids))
        )
        await session.execute(delete(Thread).where(Thread.id.in_(ids)))


@pytest.fixture
async def cleanup_reports(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of reports the test commits; deleted afterwards (``reports`` is polymorphic, so
    nothing cascades from the reported content)."""
    from sqlalchemy import delete

    from app.db.models import Report
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Report).where(Report.id.in_(ids)))


@pytest.fixture
async def cleanup_attachments(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of attachments the test commits; deleted afterwards (ids already gone are fine)."""
    from sqlalchemy import delete

    from app.db.models import Attachment
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Attachment).where(Attachment.id.in_(ids)))


TURNSTILE_GOOD_TOKEN = "good-token"


@pytest.fixture
def turnstile_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[respx.MockRouter]:
    """Turnstile enabled (as in production) with Cloudflare's siteverify mocked: only the token
    ``good-token`` passes. The router is yielded so tests can assert whether it was called."""
    from urllib.parse import parse_qs

    import httpx
    import respx

    from app.core.config import settings
    from app.services.turnstile import SITEVERIFY_URL

    def siteverify(request: httpx.Request) -> httpx.Response:
        response = parse_qs(request.content.decode()).get("response")
        return httpx.Response(200, json={"success": response == [TURNSTILE_GOOD_TOKEN]})

    monkeypatch.setattr(settings, "TURNSTILE_ENABLED", True)
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "test-turnstile-secret")
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.post(SITEVERIFY_URL).mock(side_effect=siteverify)
        yield router
