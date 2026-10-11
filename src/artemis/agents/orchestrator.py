"""The orchestrator agent.

It routes each request to one specialist via a hand-written delegation tool
(PydanticAI v2 removed ``Agent.as_tool``; the supported core pattern is a tool
that calls ``specialist.run(...)`` and forwards deps/usage/model).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from artemis.agents.budgets import budgets_agent
from artemis.agents.deps import Deps
from artemis.agents.goals import goals_agent
from artemis.agents.insights import insights_agent
from artemis.agents.portfolio import portfolio_agent
from artemis.agents.prompts import ORCHESTRATOR_INSTRUCTIONS
from artemis.agents.transactions import transactions_agent

orchestrator_agent = Agent(
    name="artemis",
    deps_type=Deps,
    output_type=str,
    instructions=ORCHESTRATOR_INSTRUCTIONS,
)


async def _delegate(ctx: RunContext[Deps], agent: Agent[Any, str], request: str) -> str:
    result = await agent.run(
        request,
        deps=ctx.deps,
        usage=ctx.usage,
        model=ctx.deps.model,
    )
    return result.output


@orchestrator_agent.tool
async def handle_transactions(ctx: RunContext[Deps], request: str) -> str:
    """Record expenses/income, search transactions, categorize, or import CSV.

    Pass the user's full request verbatim.
    """
    return await _delegate(ctx, transactions_agent, request)


@orchestrator_agent.tool
async def handle_budgets(ctx: RunContext[Deps], request: str) -> str:
    """Set budgets or report budget-vs-actual for a period."""
    return await _delegate(ctx, budgets_agent, request)


@orchestrator_agent.tool
async def handle_goals(ctx: RunContext[Deps], request: str) -> str:
    """Create savings goals, record contributions, and project progress."""
    return await _delegate(ctx, goals_agent, request)


@orchestrator_agent.tool
async def handle_portfolio(ctx: RunContext[Deps], request: str) -> str:
    """Manage holdings/prices and report allocation and unrealized P/L."""
    return await _delegate(ctx, portfolio_agent, request)


@orchestrator_agent.tool
async def handle_insights(ctx: RunContext[Deps], request: str) -> str:
    """Answer read-only spending questions (by category/merchant/period/trend)."""
    return await _delegate(ctx, insights_agent, request)


@orchestrator_agent.tool
async def handle_reports(ctx: RunContext[Deps], request: str) -> str:
    """Generate a spending report, optionally as a chart PNG and/or a PDF."""
    from artemis.agents.reports import reports_agent

    toolsets = ctx.deps.mcp.toolsets() if ctx.deps.mcp is not None else []
    result = await reports_agent.run(
        request,
        deps=ctx.deps,
        usage=ctx.usage,
        model=ctx.deps.model,
        toolsets=toolsets or None,
    )
    return result.output


@orchestrator_agent.tool
async def list_remote_agents(ctx: RunContext[Deps]) -> list[str]:
    """List configured remote A2A agents as "name: url"."""
    if ctx.deps.a2a is None:
        return []
    return [f"{peer.name}: {peer.url}" for peer in ctx.deps.a2a.peers.values()]


@orchestrator_agent.tool
async def delegate_to_remote_agent(
    ctx: RunContext[Deps], agent_url: str, message: str
) -> str:
    """Delegate a question to a configured remote A2A agent (by base URL)."""
    if ctx.deps.a2a is None:
        return "No remote A2A agents are configured."
    return await ctx.deps.a2a.call_agent(agent_url, message)
