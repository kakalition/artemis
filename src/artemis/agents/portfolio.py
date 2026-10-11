"""Portfolio sub-agent: holdings, prices, allocation, unrealized P/L."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic_ai import Agent, RunContext

from artemis.agents.deps import Deps
from artemis.agents.prompts import PORTFOLIO_INSTRUCTIONS
from artemis.agents.schemas import HoldingRecord
from artemis.domain.money import parse_amount
from artemis.domain.reports import PortfolioSummary, summarize_portfolio

portfolio_agent = Agent(
    name="portfolio",
    deps_type=Deps,
    output_type=str,
    instructions=PORTFOLIO_INSTRUCTIONS,
)


def _to_decimal(value: float | int | str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid quantity: {value!r}") from exc


def _record(ctx: RunContext[Deps], holding) -> HoldingRecord:
    snapshot = ctx.deps.repos.prices.latest(holding.symbol)
    price_minor = snapshot.price_minor if snapshot else None
    market_value = (
        int((holding.quantity * price_minor).to_integral_value()) if price_minor is not None else None
    )
    unrealized = market_value - holding.cost_basis_minor if market_value is not None else None
    return HoldingRecord(
        symbol=holding.symbol,
        quantity=holding.quantity,
        cost_basis_minor=holding.cost_basis_minor,
        price_minor=price_minor,
        market_value_minor=market_value,
        unrealized_pl_minor=unrealized,
        currency=holding.currency,
    )


@portfolio_agent.tool
async def add_holding(
    ctx: RunContext[Deps],
    symbol: str,
    quantity: float | str,
    cost_basis: str,
    currency: str | None = None,
) -> HoldingRecord:
    """Add or update a holding (total cost basis, not per-share).

    Args:
        symbol: Ticker symbol, e.g. "AAPL".
        quantity: Number of units (may be fractional).
        cost_basis: Total cost basis as a human string, e.g. "1500.00".
        currency: ISO-4217 code; defaults to USD.
    """
    currency = (currency or "USD").upper()
    holding = ctx.deps.repos.holdings.upsert(
        symbol,
        _to_decimal(quantity),
        cost_basis_minor=parse_amount(cost_basis, currency),
        currency=currency,
    )
    return _record(ctx, holding)


@portfolio_agent.tool
async def set_price(
    ctx: RunContext[Deps],
    symbol: str,
    price: str,
    currency: str | None = None,
) -> HoldingRecord | None:
    """Record a manual price snapshot for a symbol (per unit)."""
    holding = ctx.deps.repos.holdings.get_by_symbol(symbol)
    currency = (currency or (holding.currency if holding else "USD")).upper()
    ctx.deps.repos.prices.add(
        symbol, parse_amount(price, currency), currency=currency, source="manual"
    )
    return _record(ctx, holding) if holding else None


@portfolio_agent.tool
async def refresh_prices(ctx: RunContext[Deps]) -> list[HoldingRecord]:
    """Refresh prices for all holdings from the configured price source."""
    holdings = ctx.deps.repos.holdings.list()
    for holding in holdings:
        quote = await ctx.deps.price_source.quote(holding.symbol, holding.currency)
        if quote is not None:
            ctx.deps.repos.prices.add(
                holding.symbol,
                quote.price_minor,
                currency=quote.currency,
                as_of=quote.as_of,
                source=quote.source,
            )
    return [_record(ctx, h) for h in holdings]


@portfolio_agent.tool
async def get_portfolio_summary(
    ctx: RunContext[Deps], currency: str | None = None
) -> PortfolioSummary:
    """Allocation and unrealized P/L for the portfolio."""
    return summarize_portfolio(ctx.deps.repos, currency=currency)


@portfolio_agent.tool
async def list_holdings(ctx: RunContext[Deps]) -> list[HoldingRecord]:
    """List all holdings with their latest valuation."""
    return [_record(ctx, h) for h in ctx.deps.repos.holdings.list()]
