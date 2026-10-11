"""Read-only aggregates and projections.

Everything here is deterministic and money-safe: transactions are read through
the owner-scoped repositories and grouped by currency (never converted).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field

from artemis.db.repos import Repositories

# --------------------------------------------------------------------------
# Structured output models
# --------------------------------------------------------------------------


class CategoryTotal(BaseModel):
    category_id: int | None = None
    category: str
    amount_minor: int
    share: Decimal = Decimal("0")


class MerchantTotal(BaseModel):
    merchant: str
    amount_minor: int
    count: int


class TrendPoint(BaseModel):
    period: str  # "YYYY-MM"
    spend_minor: int
    income_minor: int


class SpendingReport(BaseModel):
    period_start: date
    period_end: date
    currency: str
    total_spend_minor: int
    total_income_minor: int
    net_minor: int
    transaction_count: int
    by_category: list[CategoryTotal] = Field(default_factory=list)
    top_merchants: list[MerchantTotal] = Field(default_factory=list)
    monthly_trend: list[TrendPoint] = Field(default_factory=list)
    previous_period_spend_minor: int | None = None
    change_minor: int | None = None
    change_pct: Decimal | None = None
    excluded_currencies: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BudgetLine(BaseModel):
    category_id: int
    category: str
    budget_minor: int
    spent_minor: int
    remaining_minor: int
    overspent: bool
    currency: str


class BudgetStatus(BaseModel):
    period: str
    currency: str
    lines: list[BudgetLine] = Field(default_factory=list)
    total_budget_minor: int = 0
    total_spent_minor: int = 0
    total_remaining_minor: int = 0


class GoalProjection(BaseModel):
    goal_id: int
    name: str
    target_minor: int
    contributed_minor: int
    remaining_minor: int
    currency: str
    target_date: date | None = None
    months_left: int | None = None
    required_monthly_minor: int | None = None
    monthly_contribution_minor: int | None = None
    months_to_target: int | None = None
    on_track: bool | None = None


class HoldingLine(BaseModel):
    symbol: str
    quantity: Decimal
    cost_basis_minor: int
    price_minor: int | None = None
    market_value_minor: int | None = None
    unrealized_pl_minor: int | None = None
    weight_pct: Decimal = Decimal("0")
    currency: str


class PortfolioSummary(BaseModel):
    currency: str
    total_cost_basis_minor: int
    total_market_value_minor: int
    total_unrealized_pl_minor: int
    holdings: list[HoldingLine] = Field(default_factory=list)
    as_of: date | None = None


# --------------------------------------------------------------------------
# Period helpers
# --------------------------------------------------------------------------


def _month_end(year: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last)


def period_bounds(period: str, *, today: date | None = None) -> tuple[date, date]:
    """Resolve a period string to an inclusive ``(start, end)`` date range.

    Accepts ``YYYY-MM``, ``YYYY``, ``this-month``, ``last-month``,
    ``this-year``, ``last-30-days``, and ``all``.
    """
    today = today or date.today()
    key = period.strip().lower()
    if key in {"all", "all-time", "everything"}:
        return date(1970, 1, 1), today
    if key == "this-month":
        return date(today.year, today.month, 1), _month_end(today.year, today.month)
    if key == "last-month":
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return date(year, month, 1), _month_end(year, month)
    if key == "this-year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if key == "last-year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "last-30-days":
        return today - timedelta(days=29), today
    if len(key) == 7 and key[4] == "-":
        year, month = int(key[:4]), int(key[5:])
        return date(year, month, 1), _month_end(year, month)
    if len(key) == 4 and key.isdigit():
        year = int(key)
        return date(year, 1, 1), date(year, 12, 31)
    raise ValueError(f"unrecognized period: {period!r}")


def previous_window(start: date, end: date) -> tuple[date, date]:
    """The equal-length window immediately before ``(start, end)``."""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end


# --------------------------------------------------------------------------
# Spending report
# --------------------------------------------------------------------------


def _spend(amount_minor: int) -> int:
    return -amount_minor if amount_minor < 0 else 0


def _income(amount_minor: int) -> int:
    return amount_minor if amount_minor > 0 else 0


def build_spending_report(
    repos: Repositories,
    *,
    period: str = "this-month",
    start: date | None = None,
    end: date | None = None,
    currency: str | None = None,
    top_n: int = 5,
    today: date | None = None,
) -> SpendingReport:
    """Aggregate spend for a period, grouped by currency (no FX conversion)."""
    today = today or date.today()
    if start is None or end is None:
        start, end = period_bounds(period, today=today)

    all_rows = repos.transactions.list(start=start, end=end)
    currencies = sorted({row.currency for row in all_rows})
    excluded: list[str] = []
    if currency is None:
        if currencies:
            counts: dict[str, int] = defaultdict(int)
            for row in all_rows:
                counts[row.currency] += 1
            currency = max(counts, key=lambda c: counts[c])
        else:
            currency = "USD"
    else:
        currency = currency.upper()
    excluded = [c for c in currencies if c != currency]

    rows = [row for row in all_rows if row.currency == currency]

    categories = {c.id: c.name for c in repos.categories.list()}
    category_totals: dict[int | None, int] = defaultdict(int)
    merchant_totals: dict[str, int] = defaultdict(int)
    merchant_counts: dict[str, int] = defaultdict(int)
    trend: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    total_spend = 0
    total_income = 0
    for row in rows:
        spend = _spend(row.amount_minor)
        income = _income(row.amount_minor)
        total_spend += spend
        total_income += income
        category_totals[row.category_id] += spend
        if row.merchant:
            merchant_totals[row.merchant] += spend
            merchant_counts[row.merchant] += 1
        key = f"{row.posted_at.year:04d}-{row.posted_at.month:02d}"
        trend[key][0] += spend
        trend[key][1] += income

    by_category = [
        CategoryTotal(
            category_id=cid,
            category=categories.get(cid, "Uncategorized") if cid else "Uncategorized",
            amount_minor=amount,
            share=(Decimal(amount) / Decimal(total_spend) if total_spend else Decimal("0")),
        )
        for cid, amount in sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)
        if amount > 0
    ]

    top_merchants = [
        MerchantTotal(merchant=m, amount_minor=a, count=merchant_counts[m])
        for m, a in sorted(merchant_totals.items(), key=lambda kv: kv[1], reverse=True)
        if a > 0
    ][:top_n]

    monthly_trend = [
        TrendPoint(period=p, spend_minor=s, income_minor=i)
        for p, (s, i) in sorted(trend.items())
    ]

    prev_start, prev_end = previous_window(start, end)
    prev_rows = [
        row
        for row in repos.transactions.list(start=prev_start, end=prev_end)
        if row.currency == currency
    ]
    previous_spend = sum(_spend(row.amount_minor) for row in prev_rows)

    change_minor: int | None = None
    change_pct: Decimal | None = None
    if prev_rows:
        change_minor = total_spend - previous_spend
        if previous_spend:
            change_pct = (Decimal(change_minor) / Decimal(previous_spend)).quantize(Decimal("0.0001"))

    return SpendingReport(
        period_start=start,
        period_end=end,
        currency=currency,
        total_spend_minor=total_spend,
        total_income_minor=total_income,
        net_minor=total_income - total_spend,
        transaction_count=len(rows),
        by_category=by_category,
        top_merchants=top_merchants,
        monthly_trend=monthly_trend,
        previous_period_spend_minor=previous_spend if prev_rows else None,
        change_minor=change_minor,
        change_pct=change_pct,
        excluded_currencies=excluded,
    )


def build_budget_status(
    repos: Repositories,
    *,
    period: str,
    currency: str | None = None,
) -> BudgetStatus:
    """Budget-vs-actual for a ``YYYY-MM`` period."""
    start, end = period_bounds(period)
    budgets = repos.budgets.list(period)
    currency = (
        currency.upper()
        if currency
        else (budgets[0].currency if budgets else "USD")
    )
    categories = {c.id: c.name for c in repos.categories.list()}

    spent: dict[int, int] = defaultdict(int)
    for row in repos.transactions.list(start=start, end=end, currency=currency):
        if row.category_id is not None:
            spent[row.category_id] += _spend(row.amount_minor)

    lines: list[BudgetLine] = []
    for budget in budgets:
        if budget.currency != currency:
            continue
        used = spent.get(budget.category_id, 0)
        lines.append(
            BudgetLine(
                category_id=budget.category_id,
                category=categories.get(budget.category_id, "Unknown"),
                budget_minor=budget.amount_minor,
                spent_minor=used,
                remaining_minor=budget.amount_minor - used,
                overspent=used > budget.amount_minor,
                currency=currency,
            )
        )
    lines.sort(key=lambda line: line.remaining_minor)
    return BudgetStatus(
        period=period,
        currency=currency,
        lines=lines,
        total_budget_minor=sum(line.budget_minor for line in lines),
        total_spent_minor=sum(line.spent_minor for line in lines),
        total_remaining_minor=sum(line.remaining_minor for line in lines),
    )


def _months_between(start: date, end: date) -> int:
    """Whole months (rounded up) between two dates, via ``dateutil``."""
    delta = relativedelta(end, start)
    months = delta.years * 12 + delta.months
    if delta.days > 0:
        months += 1
    return max(months, 0)


def project_goal(
    *,
    goal_id: int,
    name: str,
    target_minor: int,
    contributed_minor: int,
    currency: str = "USD",
    target_date: date | None = None,
    monthly_contribution_minor: int | None = None,
    today: date | None = None,
) -> GoalProjection:
    """Required-monthly-savings projection plus an optional what-if scenario."""
    today = today or date.today()
    remaining = max(target_minor - contributed_minor, 0)

    months_left: int | None = None
    required_monthly: int | None = None
    if target_date is not None:
        months_left = max(_months_between(today, target_date), 0)
        if months_left > 0:
            required_monthly = int(
                (Decimal(remaining) / Decimal(months_left)).to_integral_value(rounding=ROUND_CEILING)
            )
        else:
            required_monthly = remaining

    months_to_target: int | None = None
    on_track: bool | None = None
    if monthly_contribution_minor and monthly_contribution_minor > 0:
        months_to_target = int(
            (Decimal(remaining) / Decimal(monthly_contribution_minor)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        if required_monthly is not None:
            on_track = monthly_contribution_minor >= required_monthly

    return GoalProjection(
        goal_id=goal_id,
        name=name,
        target_minor=target_minor,
        contributed_minor=contributed_minor,
        remaining_minor=remaining,
        currency=currency,
        target_date=target_date,
        months_left=months_left,
        required_monthly_minor=required_monthly,
        monthly_contribution_minor=monthly_contribution_minor,
        months_to_target=months_to_target,
        on_track=on_track,
    )


def summarize_portfolio(
    repos: Repositories,
    *,
    currency: str | None = None,
) -> PortfolioSummary:
    """Mark holdings to their latest price snapshot and compute unrealized P/L."""
    holdings = repos.holdings.list()
    currency = currency.upper() if currency else (holdings[0].currency if holdings else "USD")

    lines: list[HoldingLine] = []
    total_value = 0
    total_cost = 0
    as_of: date | None = None
    for holding in holdings:
        if holding.currency != currency:
            continue
        snapshot = repos.prices.latest(holding.symbol)
        price_minor = snapshot.price_minor if snapshot else None
        market_value: int | None = None
        unrealized: int | None = None
        if price_minor is not None:
            market_value = int((holding.quantity * price_minor).to_integral_value())
            unrealized = market_value - holding.cost_basis_minor
            total_value += market_value
            if snapshot and (as_of is None or snapshot.as_of > as_of):
                as_of = snapshot.as_of
        total_cost += holding.cost_basis_minor
        lines.append(
            HoldingLine(
                symbol=holding.symbol,
                quantity=holding.quantity,
                cost_basis_minor=holding.cost_basis_minor,
                price_minor=price_minor,
                market_value_minor=market_value,
                unrealized_pl_minor=unrealized,
                currency=holding.currency,
            )
        )

    for line in lines:
        if total_value and line.market_value_minor is not None:
            line.weight_pct = (Decimal(line.market_value_minor) / Decimal(total_value)).quantize(
                Decimal("0.0001")
            )

    return PortfolioSummary(
        currency=currency,
        total_cost_basis_minor=total_cost,
        total_market_value_minor=total_value,
        total_unrealized_pl_minor=total_value - total_cost,
        holdings=lines,
        as_of=as_of,
    )
