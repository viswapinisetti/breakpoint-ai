"""Alembic environment.

The database URL and metadata come from the application rather than
alembic.ini, so migrations always target whatever `BREAKPOINT_DATABASE_URL`
the app itself is configured with. That removes the class of incident where
migrations run against a different database than the service.

`render_as_batch` is on because SQLite cannot ALTER a column in place; batch
mode rewrites the table instead. Without it, any column alteration silently
fails on the development database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401 - imported for its side effect of registering mappers

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    # The app runs migrations in-process at startup. fileConfig's default
    # disables every logger that already exists, which silenced the app's own
    # startup log from here on and made a slow start look like a hang.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting - useful for review."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
