"""Alembic runtime configuration for the Quick application database."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from xiaoying_quick.infrastructure.persistence import models as models  # noqa: F401
from xiaoying_quick.infrastructure.persistence.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    command_arguments = context.get_x_argument(as_dictionary=True)
    explicit = command_arguments.get("database_url")
    if explicit:
        return explicit
    environment_url = os.environ.get("XIAOYING_DATABASE_URL")
    if environment_url:
        return environment_url
    configured_url = config.get_main_option("sqlalchemy.url")
    if not configured_url:
        raise RuntimeError("application database URL is not configured")
    return configured_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
