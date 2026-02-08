"""Alembic migration environment configuration for SummitFlow.

SummitFlow uses raw SQL queries (psycopg) without SQLAlchemy models,
so we don't use autogenerate. Migrations are written manually.
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import config which handles ~/.env.local loading via pydantic-settings
from app.config import DATABASE_URL as _app_db_url

# this is the Alembic Config object
config = context.config

# Use DATABASE_URL from env (if explicitly set) or from app config
database_url = os.environ.get("DATABASE_URL") or _app_db_url
config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy models - SummitFlow uses raw psycopg queries
# All migrations are written manually (no autogenerate)
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This emits SQL to stdout instead of executing against the database.
    Useful for generating SQL scripts for review.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the database and executes migrations directly.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
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
