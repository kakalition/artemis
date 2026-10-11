"""Process runtime: settings -> engine -> repositories -> deps.

Owns the SQLAlchemy engine and session factory. Front-ends (CLI, Telegram) use
:func:`repositories` to get an owner-scoped :class:`Repositories` for one unit
of work.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session

from artemis.agents.deps import ApprovalCallback, Deps
from artemis.config import Settings, get_settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.db.repos import Repositories
from artemis.prices.base import ManualPriceSource, PriceSource
from artemis.prices.yfinance_source import YFinancePriceSource, yfinance_available


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    session_factory: object


def build_price_source(settings: Settings) -> PriceSource:
    if settings.price_source == "yfinance" and yfinance_available():
        return YFinancePriceSource()
    return ManualPriceSource()


def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = create_db_engine(settings.database_url, auth_token=settings.libsql_auth_token)
    bootstrap(engine, settings.owner_id, settings.owner_name)
    return Runtime(settings=settings, engine=engine, session_factory=make_session_factory(engine))


# Serialize database access: local libSQL/SQLite tolerates only one writer, and
# the A2A task store writes from worker threads while agent turns run. A single
# process-local re-entrant lock keeps concurrent writers from deadlocking on the
# file lock.
_db_lock = threading.RLock()


@contextmanager
def repositories(runtime: Runtime) -> Iterator[Repositories]:
    with _db_lock:
        session: Session = runtime.session_factory()  # type: ignore[operator]
        try:
            yield Repositories(session, runtime.settings.owner_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def build_deps(
    runtime: Runtime,
    repos: Repositories,
    *,
    model: object | None = None,
    mcp: object | None = None,
    a2a: object | None = None,
    approve: ApprovalCallback | None = None,
) -> Deps:
    return Deps(
        owner_id=runtime.settings.owner_id,
        repos=repos,
        settings=runtime.settings,
        price_source=build_price_source(runtime.settings),
        model=model,
        mcp=mcp,  # type: ignore[arg-type]
        a2a=a2a,  # type: ignore[arg-type]
        approve=approve,
    )
