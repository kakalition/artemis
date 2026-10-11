"""Artemis as an MCP server (``artemis mcp``).

Exposes the **full finance agent** through the ``ask_artemis`` tool (reads plus
normal writes such as recording transactions, budgets, goals and prices). Bulk
and destructive tools stay approval-gated; with no interactive approver over
MCP they are denied unless ``MCP_AUTO_APPROVE`` is explicitly set.

The structured read-only tools and the artifact resource are kept for clients
that want typed data. Defaults to stdio; HTTP transports bind loopback only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastmcp import FastMCP

from artemis.agents.deps import ApprovalRequest
from artemis.agents.schemas import GoalRecord
from artemis.config import Settings, build_model
from artemis.domain.money import format_minor
from artemis.domain.reports import (
    BudgetStatus,
    PortfolioSummary,
    SpendingReport,
    build_budget_status,
    build_spending_report,
    period_bounds,
    summarize_portfolio,
)
from artemis.mcp.registry import MCPRegistry
from artemis.services.runtime import Runtime, build_deps, build_runtime, repositories

INSTRUCTIONS = (
    "Artemis is a personal finance agent. Use `ask_artemis` to ask it anything "
    "in natural language — it can read the ledger and record expenses, set "
    "budgets, manage goals, and update the portfolio. Bulk/destructive actions "
    "(CSV import, deleting transactions) require approval and are denied over "
    "MCP unless the operator enables auto-approval. The structured read-only "
    "tools return exact amounts as integer minor units plus an ISO-4217 "
    "currency; never convert between currencies."
)


async def _auto_approver(requests: list[ApprovalRequest]) -> dict[str, bool]:
    return {request.tool_call_id: True for request in requests}


def build_server(
    settings: Settings,
    runtime: Runtime | None = None,
    *,
    model: object | None = None,
    registry: MCPRegistry | None = None,
    a2a_client: object | None = None,
    auto_approve: bool | None = None,
) -> FastMCP:
    runtime = runtime or build_runtime(settings)
    if auto_approve is None:
        auto_approve = settings.mcp_auto_approve

    @asynccontextmanager
    async def lifespan(server: FastMCP):
        # Own the apollo MCP toolsets for the lifetime of this server.
        if registry is not None:
            async with registry:
                yield
        else:
            yield

    mcp = FastMCP(name="artemis", instructions=INSTRUCTIONS, lifespan=lifespan)

    @mcp.tool
    async def ask_artemis(prompt: str, conversation_id: str = "mcp:default") -> str:
        """Ask the full Artemis agent (reads and writes).

        Args:
            prompt: The natural-language request.
            conversation_id: Conversation to use, so callers keep separate
                histories (default "mcp:default").
        """
        from artemis.a2a.client import build_a2a_client
        from artemis.services.session import ChatRunner

        with repositories(runtime) as repos:
            deps = build_deps(
                runtime,
                repos,
                model=model or build_model(settings),
                mcp=registry,
                a2a=a2a_client or build_a2a_client(settings),
                approve=_auto_approver if auto_approve else None,
            )
            runner = ChatRunner(deps, conversation_id=conversation_id)
            result = await runner.send(prompt)
        output = result.output
        if result.artifacts:
            lines = [f"- {a['kind']}: {a['path']}" for a in result.artifacts]
            output = f"{output}\n\nArtifacts:\n" + "\n".join(lines)
        return output

    @mcp.tool
    def query_spending(
        period: str = "this-month", currency: str | None = None, top_n: int = 5
    ) -> SpendingReport:
        """Spend by category/merchant for a period (a month like 2026-01 or a keyword)."""
        with repositories(runtime) as repos:
            return build_spending_report(repos, period=period, currency=currency, top_n=top_n)

    @mcp.tool
    def get_budget_status(period: str = "this-month", currency: str | None = None) -> BudgetStatus:
        """Budget-vs-actual for a period."""
        start, _ = period_bounds(period)
        period_key = f"{start.year:04d}-{start.month:02d}"
        with repositories(runtime) as repos:
            return build_budget_status(repos, period=period_key, currency=currency)

    @mcp.tool
    def get_portfolio_summary(currency: str | None = None) -> PortfolioSummary:
        """Holdings, allocation, market value, and unrealized P/L."""
        with repositories(runtime) as repos:
            return summarize_portfolio(repos, currency=currency)

    @mcp.tool
    def list_goals() -> list[GoalRecord]:
        """List savings goals with progress."""
        with repositories(runtime) as repos:
            records = []
            for goal in repos.goals.list():
                assert goal.id is not None
                contributed = repos.goals.contributed_minor(goal.id)
                records.append(
                    GoalRecord(
                        id=goal.id,
                        name=goal.name,
                        target_minor=goal.target_minor,
                        target_display=format_minor(goal.target_minor, goal.currency),
                        contributed_minor=contributed,
                        contributed_display=format_minor(contributed, goal.currency),
                        remaining_minor=max(goal.target_minor - contributed, 0),
                        currency=goal.currency,
                        target_date=goal.target_date,
                    )
                )
            return records

    @mcp.resource("artemis://artifact/{name}")
    def artifact(name: str) -> str:
        """Read a generated report artifact (chart/PDF) by file name."""
        base = settings.artifacts_dir.resolve()
        candidate = (base / name).resolve()
        if base not in candidate.parents or not candidate.is_file():
            raise ValueError(f"unknown artifact: {name}")
        if candidate.suffix.lower() in {".txt", ".md", ".csv", ".json"}:
            return candidate.read_text(encoding="utf-8")
        return str(candidate)

    return mcp


def serve(
    settings: Settings,
    *,
    transport: str = "stdio",
    host: str | None = None,
    port: int | None = None,
) -> None:
    from artemis.guardrails import warn_if_exposed

    runtime = build_runtime(settings)
    registry = MCPRegistry(settings)
    host = host or settings.mcp_host
    port = port or settings.mcp_port
    if transport != "stdio":
        warn_if_exposed(host, "the Artemis MCP server")
    mcp = build_server(settings, runtime, registry=registry)
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in {"streamable-http", "http"}:
        mcp.run(transport="http", host=host, port=port)
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        raise ValueError(f"unsupported transport: {transport!r}")
