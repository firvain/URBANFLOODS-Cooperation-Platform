"""Async database engine, session factory, and readiness check."""

import asyncio
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

READINESS_TIMEOUT_SECONDS = 2.0

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

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
