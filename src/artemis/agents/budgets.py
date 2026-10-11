"""Budgets sub-agent: set budgets and report budget-vs-actual."""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from artemis.agents.deps import Deps
from artemis.agents.prompts import BUDGETS_INSTRUCTIONS
from artemis.agents.schemas import BudgetRecord
from artemis.domain.money import format_minor, parse_amount
from artemis.domain.reports import BudgetStatus, build_budget_status, period_bounds
from artemis.services import ledger

budgets_agent = Agent(
    name="budgets",
    deps_type=Deps,
    output_type=str,
    instructions=BUDGETS_INSTRUCTIONS,
)


def _record(ctx: RunContext[Deps], budget, period: str | None = None) -> BudgetRecord:
    category = ctx.deps.repos.categories.get(budget.category_id)
    return BudgetRecord(
        category=category.name if category else "Unknown",
        period=period or budget.period,
        amount_minor=budget.amount_minor,
        amount_display=format_minor(budget.amount_minor, budget.currency),
        currency=budget.currency,
    )


@budgets_agent.tool
async def set_budget(
    ctx: RunContext[Deps],
    category: str,
    amount: str,
    period: str = "this-month",
    currency: str | None = None,
) -> BudgetRecord:
    """Set the budget for a category and period (e.g. "2026-01" or "this-month").

    Args:
        category: Category name (created if missing).
        amount: Budget amount as a human string, e.g. "500" or "$500.00".
        period: A month like "2026-01", or a keyword (this-month, last-month).
        currency: ISO-4217 code; defaults to USD.
    """
    start, _ = period_bounds(period)
    period_key = f"{start.year:04d}-{start.month:02d}"
    currency = (currency or "USD").upper()
    amount_minor = parse_amount(amount, currency)
    category_model = ledger.resolve_category(ctx.deps, category)
    assert category_model is not None and category_model.id is not None
    budget = ctx.deps.repos.budgets.upsert(category_model.id, period_key, amount_minor, currency)
    return _record(ctx, budget, period_key)


@budgets_agent.tool
async def get_budget_status(
    ctx: RunContext[Deps],
    period: str = "this-month",
    currency: str | None = None,
) -> BudgetStatus:
    """Budget-vs-actual for a period, with remaining/overspend per category."""
    start, _ = period_bounds(period)
    period_key = f"{start.year:04d}-{start.month:02d}"
    return build_budget_status(ctx.deps.repos, period=period_key, currency=currency)


@budgets_agent.tool
async def list_budgets(ctx: RunContext[Deps], period: str | None = None) -> list[BudgetRecord]:
    """List configured budgets, optionally filtered to one period."""
    period_key = None
    if period:
        start, _ = period_bounds(period)
        period_key = f"{start.year:04d}-{start.month:02d}"
    return [_record(ctx, b, b.period) for b in ctx.deps.repos.budgets.list(period_key)]
