"""Reports sub-agent.

Owns the chart (apollo-charting) and PDF (apollo-pdf-creator) MCP toolsets: it
turns a :class:`SpendingReport` into a chart PNG and/or a PDF. The toolsets are
supplied per run from :class:`~artemis.mcp.registry.MCPRegistry` (owned by the
process), so they are not baked into the agent.
"""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from artemis.agents.deps import Deps
from artemis.agents.prompts import REPORTS_INSTRUCTIONS
from artemis.domain.reports import SpendingReport, build_spending_report
from artemis.services import ledger

reports_agent = Agent(
    name="reports",
    deps_type=Deps,
    output_type=str,
    instructions=REPORTS_INSTRUCTIONS,
)


@reports_agent.tool
async def analyze_spending(
    ctx: RunContext[Deps],
    period: str = "this-month",
    start: str | None = None,
    end: str | None = None,
    currency: str | None = None,
    top_n: int = 8,
) -> SpendingReport:
    """Compute the structured spending analysis to base a report on."""
    return build_spending_report(
        ctx.deps.repos,
        period=period,
        start=ledger.parse_date(start) if start else None,
        end=ledger.parse_date(end) if end else None,
        currency=currency,
        top_n=top_n,
    )


@reports_agent.tool
async def read_chart_schema(ctx: RunContext[Deps]) -> str:
    """Fetch the apollo-charting spec schema (untrusted reference data)."""
    if ctx.deps.mcp is None:
        return "charting MCP server is not configured"
    try:
        return await ctx.deps.mcp.read_resource("chart", "charting://schema")
    except Exception as exc:  # pragma: no cover
        return f"charting schema unavailable: {exc}"


@reports_agent.tool
async def read_pdf_schema(ctx: RunContext[Deps]) -> str:
    """Fetch the apollo-pdf-creator spec schema (untrusted reference data)."""
    if ctx.deps.mcp is None:
        return "pdf MCP server is not configured"
    try:
        return await ctx.deps.mcp.read_resource("pdf", "pdfcreator://schema")
    except Exception as exc:  # pragma: no cover
        return f"pdf schema unavailable: {exc}"
