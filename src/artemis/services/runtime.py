"""Process runtime: settings -> engine -> repositories -> deps.

``Runtime`` is duck-type compatible with :class:`agentkit.runtime.Runtime`, and
``repositories`` delegates to agentkit so there is a single process-wide write
lock shared by the app and the A2A task store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.runtime import repositories as _agentkit_repositories
from sqlalchemy import Engine

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
    repos_factory: type = field(default=Repositories)


def build_price_source(settings: Settings) -> PriceSource:
    if settings.price_source == "yfinance" and yfinance_available():
        return YFinancePriceSource()
    return ManualPriceSource()


def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = create_db_engine(settings.resolved_database_url, auth_token=settings.libsql_auth_token)
    bootstrap(engine, settings.owner_id, settings.owner_name)
    return Runtime(settings=settings, engine=engine, session_factory=make_session_factory(engine))


def repositories(runtime: Runtime):
    """Owner-scoped repositories (shared lock, from agentkit)."""
    return _agentkit_repositories(runtime)


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
        settings=runtime.settings,
        repos=repos,
        price_source=build_price_source(runtime.settings),
        model=model,
        mcp=mcp,  # type: ignore[arg-type]
        a2a=a2a,  # type: ignore[arg-type]
        approve=approve,
    )
