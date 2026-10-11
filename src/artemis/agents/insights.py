"""Insights sub-agent: read-only Q&A over transactions."""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from artemis.agents.deps import Deps
from artemis.agents.prompts import INSIGHTS_INSTRUCTIONS
from artemis.domain.reports import SpendingReport, build_spending_report
from artemis.services import ledger

insights_agent = Agent(
    name="insights",
    deps_type=Deps,
    output_type=str,
    instructions=INSIGHTS_INSTRUCTIONS,
)


@insights_agent.tool
async def spending_report(
    ctx: RunContext[Deps],
    period: str = "this-month",
    start: str | None = None,
    end: str | None = None,
    currency: str | None = None,
    top_n: int = 5,
) -> SpendingReport:
    """Aggregate spend by category/merchant for a period.

    Args:
        period: A month ("2026-01") or keyword (this-month, last-month,
            this-year, last-30-days, all).
        start/end: Optional explicit ISO dates overriding ``period``.
        currency: Restrict to one ISO-4217 currency (defaults to the dominant).
        top_n: How many top merchants to include.
    """
    return build_spending_report(
        ctx.deps.repos,
        period=period,
        start=ledger.parse_date(start) if start else None,
        end=ledger.parse_date(end) if end else None,
        currency=currency,
        top_n=top_n,
    )
