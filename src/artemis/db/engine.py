"""libSQL / SQLite engine wiring.

The database is libSQL (SQLite-compatible) so the same code runs against a
local file and against a remote Turso database. The SAME repo interface is used
for both; only the SQLAlchemy URL / auth token differ.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session


def create_db_engine(database_url: str, *, auth_token: str | None = None, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for a libSQL/SQLite URL.

    ``database_url`` examples::

        sqlite+libsql:///absolute/path/artemis.db     # local file
        sqlite+libsql://<db>-<org>.turso.io?secure=true  # remote Turso

    For local SQLite/libSQL files we enable WAL and a busy timeout so
    concurrent writers (e.g. the A2A task store writing from a worker thread
    while an agent turn runs) wait instead of failing with "database is locked".
    """
    connect_args: dict[str, Any] = {}
    if auth_token:
        connect_args["auth_token"] = auth_token
    engine = create_engine(database_url, connect_args=connect_args, echo=echo, future=True)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()
            except Exception:  # pragma: no cover - best effort
                pass

    return engine


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
