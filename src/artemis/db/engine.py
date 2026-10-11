"""libSQL / SQLite engine wiring.

The database is libSQL (SQLite-compatible) so the same code runs against a
local file and against a remote Turso database. The SAME repo interface is used
for both; only the SQLAlchemy URL / auth token differ.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session


def create_db_engine(database_url: str, *, auth_token: str | None = None, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for a libSQL/SQLite URL.

    ``database_url`` examples::

        sqlite+libsql:///absolute/path/artemis.db     # local file
        sqlite+libsql://<db>-<org>.turso.io?secure=true  # remote Turso
    """
    connect_args: dict[str, Any] = {}
    if auth_token:
        connect_args["auth_token"] = auth_token
    return create_engine(database_url, connect_args=connect_args, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
