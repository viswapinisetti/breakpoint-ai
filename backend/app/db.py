"""Database engine and session handling."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Bring the database up to date, then verify it matches the models.

    Schema is owned by Alembic. `create_all` remains as the bootstrap path for
    a brand-new database (and for tests, which spin up throwaway files), but an
    existing database is migrated rather than patched, because `create_all`
    adds tables and never columns.

    The drift check afterwards is the safety net: if a database is still behind
    the models, say exactly which columns are missing instead of failing later
    with an opaque OperationalError mid-request.
    """
    from sqlalchemy import inspect

    from app import models  # noqa: F401 - registers mappers

    inspector = inspect(engine)

    if not inspector.has_table("challenges"):
        # Brand-new database: build it from the models and mark it current.
        Base.metadata.create_all(engine)
        _stamp_head()
    elif not inspector.has_table("alembic_version"):
        # A database created before migrations existed. Running the initial
        # migration would try to CREATE TABLE over live tables, so adopt it
        # instead - but only if it already matches the models. Otherwise say
        # so, rather than stamping a mismatched schema as current.
        missing = _drift(inspect(engine))
        if missing:
            raise RuntimeError(
                "This database predates migrations and is missing columns: "
                f"{', '.join(missing)}. Recreate it (development) or migrate it "
                "by hand and then run `alembic stamp head`."
            )
        logger.info("adopting pre-migration database: stamping at head")
        _stamp_head()
    else:
        _upgrade_head()

    drift = _drift(inspect(engine))
    if drift:
        logger.error(
            "Database schema is out of date - missing columns: %s. "
            "Run `alembic upgrade head`, or in development delete the database "
            "and let it re-seed from content files.",
            ", ".join(drift),
        )
        raise RuntimeError(f"schema drift: {', '.join(drift)}")


def _drift(inspector) -> list[str]:
    """Columns present in the models but absent from the database."""
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        actual = {c["name"] for c in inspector.get_columns(table_name)}
        gap = {c.name for c in table.columns} - actual
        missing.extend(f"{table_name}.{col}" for col in sorted(gap))
    return missing


def _alembic_config():
    """Alembic config pointed at this app's database and migrations."""
    from alembic.config import Config

    from app.config import BASE_DIR

    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _stamp_head() -> None:
    """Mark a freshly created database as already at the latest revision."""
    from alembic import command

    command.stamp(_alembic_config(), "head")


def _upgrade_head() -> None:
    """Apply any pending migrations to an existing database."""
    from alembic import command

    logger.info("applying database migrations")
    command.upgrade(_alembic_config(), "head")
