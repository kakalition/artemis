"""Agent tests using FunctionModel — no network, no real LLM calls."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from artemis.agents.budgets import budgets_agent
from artemis.agents.deps import Deps
from artemis.agents.goals import goals_agent
from artemis.agents.insights import insights_agent
from artemis.agents.orchestrator import orchestrator_agent
from artemis.agents.portfolio import portfolio_agent
from artemis.agents.transactions import transactions_agent
from artemis.config import Settings
from artemis.prices.base import ManualPriceSource


@pytest.fixture
def agent_deps(repos) -> Deps:
    return Deps(
        repos=repos,
        settings=Settings(owner_id="owner"),
        price_source=ManualPriceSource(),
    )


def _tool_names(agent) -> set[str]:
    return set(agent._function_toolset.tools.keys())


def _has_tool_return(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in getattr(message, "parts", [])
    )


def test_sub_agent_tool_names():
    assert _tool_names(transactions_agent) >= {
        "record_transaction",
        "list_transactions",
        "import_transactions",
        "delete_transaction",
    }
    assert _tool_names(budgets_agent) >= {"set_budget", "get_budget_status"}
    assert _tool_names(goals_agent) >= {"create_goal", "add_contribution", "project_goal_progress"}
    assert _tool_names(portfolio_agent) >= {
        "add_holding",
        "set_price",
        "refresh_prices",
        "get_portfolio_summary",
    }
    assert _tool_names(insights_agent) >= {"spending_report"}


def test_import_and_delete_require_approval():
    tools = transactions_agent._function_toolset.tools
    assert tools["import_transactions"].requires_approval is True
    assert tools["delete_transaction"].requires_approval is True
    assert tools["list_transactions"].requires_approval is False


def test_orchestrator_tools():
    assert _tool_names(orchestrator_agent) >= {
        "handle_transactions",
        "handle_budgets",
        "handle_goals",
        "handle_portfolio",
        "handle_insights",
        "delegate_to_remote_agent",
    }


async def test_transactions_agent_records_transaction(agent_deps):
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _has_tool_return(messages):
            return ModelResponse(parts=[TextPart("recorded")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "record_transaction",
                    {"amount": "-42.50", "description": "lunch", "merchant": "Cafe Rio"},
                )
            ]
        )

    result = await transactions_agent.run(
        "spent $42.50 at Cafe Rio", deps=agent_deps, model=FunctionModel(model_fn)
    )
    assert result.output == "recorded"
    rows = agent_deps.repos.transactions.list()
    assert len(rows) == 1
    assert rows[0].amount_minor == -4250
    assert rows[0].merchant == "Cafe Rio"


async def test_orchestrator_delegates_to_transactions(agent_deps):
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool_names = {tool.name for tool in info.function_tools}
        if "handle_transactions" in tool_names:  # the orchestrator
            if _has_tool_return(messages):
                return ModelResponse(parts=[TextPart("routed")])
            return ModelResponse(
                parts=[ToolCallPart("handle_transactions", {"request": "list categories"})]
            )
        return ModelResponse(parts=[TextPart("transactions handled")])

    model = FunctionModel(model_fn)
    agent_deps.model = model
    result = await orchestrator_agent.run("what categories do I have?", deps=agent_deps, model=model)
    assert result.output == "routed"


async def _run_import(agent_deps, approve_result: bool):
    seen: list[list] = []

    async def approve(requests):
        seen.append(list(requests))
        return {r.tool_call_id: approve_result for r in requests}

    agent_deps.approve = approve

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        if "import_transactions" in names:  # the transactions sub-agent
            if _has_tool_return(messages):
                return ModelResponse(parts=[TextPart("imported")])
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "import_transactions",
                        {"csv_text": "date,amount,description\n2026-01-05,-10.00,Coffee\n"},
                    )
                ]
            )
        if _has_tool_return(messages):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart("handle_transactions", {"request": "import this csv"})]
        )

    model = FunctionModel(model_fn)
    agent_deps.model = model
    result = await orchestrator_agent.run("import this csv", deps=agent_deps, model=model)
    return result, seen


async def test_approval_grants_bulk_import(agent_deps):
    result, seen = await _run_import(agent_deps, approve_result=True)
    assert result.output == "done"
    assert len(seen) == 1
    assert seen[0][0].tool_name == "import_transactions"
    assert agent_deps.repos.transactions.count() == 1


async def test_approval_denies_bulk_import(agent_deps):
    result, seen = await _run_import(agent_deps, approve_result=False)
    assert result.output == "done"
    assert len(seen) == 1
    assert agent_deps.repos.transactions.count() == 0


async def test_approval_denied_without_callback(agent_deps):
    # No approve callback: destructive/bulk actions are denied by default.
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        if "import_transactions" in names:
            if _has_tool_return(messages):
                return ModelResponse(parts=[TextPart("imported")])
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "import_transactions",
                        {"csv_text": "date,amount\n2026-01-05,-10.00\n"},
                    )
                ]
            )
        if _has_tool_return(messages):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart("handle_transactions", {"request": "import"})]
        )

    model = FunctionModel(model_fn)
    agent_deps.model = model
    await orchestrator_agent.run("import", deps=agent_deps, model=model)
    assert agent_deps.repos.transactions.count() == 0


async def test_insights_agent_spending_report(agent_deps, sample_transactions):
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _has_tool_return(messages):
            return ModelResponse(parts=[TextPart("summary done")])
        return ModelResponse(
            parts=[ToolCallPart("spending_report", {"period": "2026-01"})]
        )

    result = await insights_agent.run(
        "how much did I spend in January?", deps=agent_deps, model=FunctionModel(model_fn)
    )
    assert result.output == "summary done"
