"""Tests for Artemis's own read-only MCP server (in-process)."""

from __future__ import annotations

from datetime import date

from fastmcp import Client
from sqlmodel import Session

from artemis.config import Settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.db.repos import Repositories
from artemis.mcp.server import build_server
from artemis.services.runtime import Runtime


def _runtime(tmp_path) -> Runtime:
    engine = create_db_engine(f"sqlite+libsql:///{tmp_path / 'artemis.db'}")
    bootstrap(engine, "owner", "Owner")
    return Runtime(
        settings=Settings(owner_id="owner", artemis_home=tmp_path),
        engine=engine,
        session_factory=make_session_factory(engine),
    )


def _seed(runtime: Runtime) -> None:
    with Session(runtime.engine) as session:
        repos = Repositories(session, "owner")
        repos.transactions.add(posted_at=date(2026, 1, 5), amount_minor=-4250, merchant="Whole Foods")
        repos.transactions.add(posted_at=date(2026, 1, 6), amount_minor=-1000, merchant="Cafe")
        goal = repos.goals.create("Holiday", 100000)
        repos.goals.add_contribution(goal.id, 25000)
        repos.holdings.upsert("AAPL", 2, cost_basis_minor=30000)
        repos.prices.add("AAPL", 16000)
        session.commit()


async def test_read_only_tools(tmp_path):
    runtime = _runtime(tmp_path)
    _seed(runtime)
    server = build_server(runtime.settings, runtime)

    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert {"query_spending", "get_budget_status", "get_portfolio_summary", "list_goals"} <= tools

        def unwrap(result) -> object:
            data = result.structured_content
            if isinstance(data, dict) and set(data.keys()) == {"result"}:
                return data["result"]
            return data

        spending = unwrap(await client.call_tool("query_spending", {"period": "2026-01"}))
        assert spending["currency"] == "USD"
        assert spending["total_spend_minor"] == 5250

        portfolio = unwrap(await client.call_tool("get_portfolio_summary", {}))
        assert portfolio["total_market_value_minor"] == 32000

        goals = unwrap(await client.call_tool("list_goals", {}))
        assert goals[0]["remaining_minor"] == 75000


async def test_no_write_tools_exposed(tmp_path):
    runtime = _runtime(tmp_path)
    _seed(runtime)
    server = build_server(runtime.settings, runtime)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
    for forbidden in ("record_transaction", "import_transactions", "delete_transaction", "set_budget"):
        assert forbidden not in names
