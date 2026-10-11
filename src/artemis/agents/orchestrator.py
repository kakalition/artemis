"""The orchestrator agent — routes requests to specialists via agentkit."""

from __future__ import annotations

from agentkit.orchestrator import Orchestrator
from pydantic_ai import RunContext

from artemis.agents.budgets import budgets_agent
from artemis.agents.deps import Deps
from artemis.agents.goals import goals_agent
from artemis.agents.insights import insights_agent
from artemis.agents.portfolio import portfolio_agent
from artemis.agents.prompts import ORCHESTRATOR_INSTRUCTIONS
from artemis.agents.transactions import transactions_agent

_orchestrator = Orchestrator(
    name="artemis",
    instructions=ORCHESTRATOR_INSTRUCTIONS,
    deps_type=Deps,
)

for _agent, _tool, _description in (
    (
        transactions_agent,
        "handle_transactions",
        "Record expenses/income, search transactions, categorize, or import CSV.",
    ),
    (budgets_agent, "handle_budgets", "Set budgets or report budget-vs-actual for a period."),
    (
        goals_agent,
        "handle_goals",
        "Create savings goals, record contributions, and project progress.",
    ),
    (
        portfolio_agent,
        "handle_portfolio",
        "Manage holdings/prices and report allocation and unrealized P/L.",
    ),
    (insights_agent, "handle_insights", "Answer read-only spending questions."),
):
    _orchestrator.add_specialist(_agent, tool_name=_tool, description=_description)

orchestrator_agent = _orchestrator.agent


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
