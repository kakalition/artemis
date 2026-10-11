"""Alembic environment wired to Artemis settings and SQLModel metadata.

The database URL is taken from ``ARTEMIS_DATABASE_URL`` when set (used by tests
and CI), otherwise from :class:`artemis.config.Settings` (local libSQL file).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import artemis.db.models  # noqa: F401  (register tables on SQLModel.metadata)
from artemis.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _database_url() -> str:
    url = os.environ.get("ARTEMIS_DATABASE_URL")
    if url:
        return url
    settings = get_settings()
    settings.ensure_dirs()
    return settings.resolved_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), future=True)
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
