"""Artemis as an MCP server (``artemis mcp``).

Exposes **read-only** finance tools so other agents can query the ledger.
Writes are deliberately not exposed. Defaults to stdio; HTTP transports bind
loopback only.
"""

from __future__ import annotations

from fastmcp import FastMCP

from artemis.agents.schemas import GoalRecord
from artemis.config import Settings
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
from artemis.services.runtime import Runtime, build_runtime, repositories

INSTRUCTIONS = (
    "Read-only access to the owner's personal finances. All amounts are integer "
    "minor units plus an ISO-4217 currency; never convert between currencies. "
    "This server cannot modify any data."
)


def build_server(settings: Settings, runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime(settings)
    mcp = FastMCP(name="artemis", instructions=INSTRUCTIONS)

    @mcp.tool
    def query_spending(
        period: str = "this-month", currency: str | None = None, top_n: int = 5
    ) -> SpendingReport:
        """Spend by category/merchant for a period (a month like 2026-01 or a keyword)."""
        with repositories(runtime) as repos:
            return build_spending_report(
                repos, period=period, currency=currency, top_n=top_n
            )

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
    mcp = build_server(settings, runtime)
    host = host or settings.mcp_host
    port = port or settings.mcp_port
    if transport != "stdio":
        warn_if_exposed(host, "the Artemis MCP server")
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in {"streamable-http", "http"}:
        mcp.run(transport="http", host=host, port=port)
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        raise ValueError(f"unsupported transport: {transport!r}")
