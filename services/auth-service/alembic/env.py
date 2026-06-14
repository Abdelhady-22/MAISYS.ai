"""Alembic migration environment for auth-service.

Async-aware: when invoked online (against a real database) we open an
``AsyncEngine`` and dispatch migrations through ``run_sync``. The
migrations themselves are sync (op.create_table, etc.) — only the
connection is async.

DATABASE_URL takes precedence over the ``sqlalchemy.url`` value in
alembic.ini, so the same migration runs against:
  * Postgres (asyncpg) in production / staging
  * SQLite (aiosqlite) in unit tests
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure the auth-service directory and the repo root are on the path so
# we can import both the service's models and the shared modules.
_SERVICE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SERVICE_DIR.parent.parent
sys.path.insert(0, str(_SERVICE_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from shared.models import Base  # noqa: E402

# Import models so they register on Base.metadata. The noqa is intentional
# — the import is a side effect (table registration) not a name we use.
import models.db  # noqa: E402, F401

config = context.config

# Override the URL from env if provided. This is how the migration runs
# against the configured database in any environment.
_env_url = os.environ.get("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render UUID columns as TEXT on SQLite, UUID on Postgres.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine and run migrations through run_sync."""
    section = config.get_section(config.config_ini_section) or {}
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
