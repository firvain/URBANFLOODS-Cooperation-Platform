"""Async database engine, session factory, and readiness check."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg.exceptions
import structlog
from sqlalchemy import event, text
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

READINESS_TIMEOUT_SECONDS = 2.0

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)


@event.listens_for(engine.sync_engine, "handle_error")
def _translate_data_errors(context: ExceptionContext) -> DataError | None:
    """Raise asyncpg's ``DataError`` family (SQLSTATE class 22, and asyncpg's own argument
    encoding errors) as ``sqlalchemy.exc.DataError``, as the DB-API defines it. The asyncpg
    dialect leaves them a plain ``DBAPIError``, so the API's handler for invalid values
    (``core/exceptions.py``) could not be registered for them alone (7n)."""
    wrapped = context.sqlalchemy_exception
    cause = context.original_exception.__cause__
    if (
        wrapped is None
        or isinstance(wrapped, DataError)
        or not isinstance(cause, asyncpg.exceptions.DataError)
    ):
        return None
    return DataError(
        wrapped.statement,
        wrapped.params,
        wrapped.orig,
        hide_parameters=wrapped.hide_parameters,
        connection_invalidated=wrapped.connection_invalidated,
    )


AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

log = structlog.get_logger(__name__)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database() -> bool:
    """Return True if ``SELECT 1`` succeeds within the timeout. Never raises."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            # Look up the module-level engine at call time so it can be swapped in tests.
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("database_unreachable", error=type(exc).__name__)
        return False
    return True
