"""Alembic environment (async, SQLAlchemy 2.x).

Two online modes, following the Alembic cookbook ("Programmatic API use (connection sharing)
With Asyncio"):

* CLI (``alembic upgrade head``): no connection is supplied, so an async engine is built from
  ``settings.DATABASE_URL`` and the migrations run through ``AsyncConnection.run_sync`` under
  ``asyncio.run``.
* Programmatic (``app.db.migrations``): the caller passes a sync ``Connection`` in
  ``config.attributes["connection"]`` (typically from ``AsyncConnection.run_sync``), and it is
  used directly. This is what lets tests migrate from inside a running event loop, where
  ``asyncio.run`` is not allowed.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.models import Base

config = context.config

# Only the CLI configures logging from alembic.ini; programmatic callers own their logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``) without connecting."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        asyncio.run(run_async_migrations())
    else:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
