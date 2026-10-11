"""Tests for Artemis's MCP server (full agent + read-only tools), in-process."""

from __future__ import annotations

from datetime import date

from fastmcp import Client
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlmodel import Session

from artemis.a2a.client import A2AClient
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


def _count(runtime: Runtime) -> int:
    with Session(runtime.engine) as session:
        return Repositories(session, "owner").transactions.count()


def _has_tool_return(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in getattr(message, "parts", [])
    )


def _delegating_model(action: str) -> FunctionModel:
    """Orchestrator -> transactions sub-agent -> ``action`` tool call."""

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        if action in names:  # the transactions sub-agent
            if _has_tool_return(messages):
                return ModelResponse(parts=[TextPart("sub-done")])
            if action == "record_transaction":
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "record_transaction",
                            {"amount": "-5.00", "description": "coffee", "merchant": "Cafe"},
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "import_transactions",
                        {"csv_text": "date,amount,description\n2026-01-05,-9.99,Coffee\n"},
                    )
                ]
            )
        if _has_tool_return(messages):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("handle_transactions", {"request": "do it"})])

    return FunctionModel(fn)


def _server(runtime: Runtime, action: str, *, auto_approve: bool | None = None):
    return build_server(
        runtime.settings,
        runtime,
        model=_delegating_model(action),
        registry=None,
        a2a_client=A2AClient(),
        auto_approve=auto_approve,
    )


async def test_tools_expose_agent_and_reads(tmp_path):
    runtime = _runtime(tmp_path)
    server = _server(runtime, "record_transaction")
    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert "ask_artemis" in tools
    assert {"query_spending", "get_budget_status", "get_portfolio_summary", "list_goals"} <= tools


async def test_ask_artemis_runs_full_agent_and_writes(tmp_path):
    runtime = _runtime(tmp_path)
    server = _server(runtime, "record_transaction")
    async with Client(server) as client:
        result = await client.call_tool("ask_artemis", {"prompt": "log $5 coffee at Cafe"})
    assert result.structured_content is not None or result.content
    assert _count(runtime) == 1


async def test_bulk_write_denied_by_default(tmp_path):
    runtime = _runtime(tmp_path)
    server = _server(runtime, "import_transactions", auto_approve=False)
    async with Client(server) as client:
        await client.call_tool("ask_artemis", {"prompt": "import this csv"})
    assert _count(runtime) == 0


async def test_bulk_write_allowed_when_auto_approve(tmp_path):
    runtime = _runtime(tmp_path)
    server = _server(runtime, "import_transactions", auto_approve=True)
    async with Client(server) as client:
        await client.call_tool("ask_artemis", {"prompt": "import this csv"})
    assert _count(runtime) == 1


async def test_read_only_tools(tmp_path):
    runtime = _runtime(tmp_path)
    with Session(runtime.engine) as session:
        repos = Repositories(session, "owner")
        repos.transactions.add(posted_at=date(2026, 1, 5), amount_minor=-4250, merchant="Whole Foods")
        repos.transactions.add(posted_at=date(2026, 1, 6), amount_minor=-1000, merchant="Cafe")
        goal = repos.goals.create("Holiday", 100000)
        repos.goals.add_contribution(goal.id, 25000)
        repos.holdings.upsert("AAPL", 2, cost_basis_minor=30000)
        repos.prices.add("AAPL", 16000)
        session.commit()

    server = build_server(runtime.settings, runtime, registry=None, a2a_client=A2AClient())
    async with Client(server) as client:
        def unwrap(result) -> object:
            data = result.structured_content
            if isinstance(data, dict) and set(data.keys()) == {"result"}:
                return data["result"]
            return data

        spending = unwrap(await client.call_tool("query_spending", {"period": "2026-01"}))
        assert spending["total_spend_minor"] == 5250
        portfolio = unwrap(await client.call_tool("get_portfolio_summary", {}))
        assert portfolio["total_market_value_minor"] == 32000
        goals = unwrap(await client.call_tool("list_goals", {}))
        assert goals[0]["remaining_minor"] == 75000


async def test_no_raw_write_tools_exposed(tmp_path):
    runtime = _runtime(tmp_path)
    server = _server(runtime, "record_transaction")
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
    for forbidden in ("record_transaction", "import_transactions", "delete_transaction", "set_budget"):
        assert forbidden not in names
