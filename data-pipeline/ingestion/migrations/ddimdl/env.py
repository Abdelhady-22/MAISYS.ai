"""Alembic environment for the ddimdl migration scope.

Run with::

    alembic -c data-pipeline/ingestion/migrations/ddimdl/alembic.ini upgrade head

``DDIMDL_DATABASE_URL`` overrides the URL configured in
``alembic.ini``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from data_pipeline.ingestion.ddimdl_postgres_ingester import Base  # type: ignore[import-not-found]

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if (url := os.environ.get("DDIMDL_DATABASE_URL")) is not None:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
