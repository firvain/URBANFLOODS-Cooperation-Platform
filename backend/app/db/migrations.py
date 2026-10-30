"""Programmatic Alembic helpers, used by tests and tooling.

From synchronous code with no event loop running, call ``upgrade_head()`` directly: ``env.py``
builds its own async engine and runs it under ``asyncio.run``.

From async code (an event loop is already running, so ``asyncio.run`` is not allowed), pass a
connection through ``run_sync`` instead; ``env.py`` then uses it as-is::

    async with engine.begin() as conn:
        await conn.run_sync(upgrade_head)
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(connection: Connection | None = None) -> Config:
    """Alembic config for ``backend/alembic.ini``, independent of the working directory."""
    cfg = Config(str(ALEMBIC_INI))
    # Do not let env.py's fileConfig() reconfigure the caller's logging.
    cfg.attributes["configure_logger"] = False
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def upgrade_head(connection: Connection | None = None) -> None:
    command.upgrade(alembic_config(connection), "head")


def downgrade_base(connection: Connection | None = None) -> None:
    command.downgrade(alembic_config(connection), "base")
