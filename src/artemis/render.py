"""Human-readable text rendering and report artifact spec builders."""

from __future__ import annotations

from decimal import Decimal

from artemis.domain.money import format_minor
from artemis.domain.reports import (
    BudgetStatus,
    GoalProjection,
    PortfolioSummary,
    SpendingReport,
)


def _major(minor: int, currency: str) -> Decimal:
    from artemis.domain.money import minor_to_decimal

    return minor_to_decimal(minor, currency)


def _fmt_quantity(quantity: Decimal) -> str:
    text = format(quantity.normalize(), "f")
    return text if text else "0"


def render_spending_report(report: SpendingReport) -> str:
    lines = [
        f"Spending report — {report.period_start} to {report.period_end} ({report.currency})",
        f"  Spend:   {format_minor(report.total_spend_minor, report.currency)}",
        f"  Income:  {format_minor(report.total_income_minor, report.currency)}",
        f"  Net:     {format_minor(report.net_minor, report.currency)}",
        f"  Transactions: {report.transaction_count}",
    ]
    if report.change_minor is not None:
        sign = "+" if report.change_minor >= 0 else ""
        lines.append(
            f"  vs previous period: {sign}{format_minor(report.change_minor, report.currency)}"
        )
    if report.by_category:
        lines.append("By category:")
        for item in report.by_category:
            share = f" ({item.share * 100:.1f}%)" if item.share else ""
            lines.append(f"  - {item.category}: {format_minor(item.amount_minor, report.currency)}{share}")
    if report.top_merchants:
        lines.append("Top merchants:")
        for merchant in report.top_merchants:
            lines.append(
                f"  - {merchant.merchant}: {format_minor(merchant.amount_minor, report.currency)}"
                f" ({merchant.count} txns)"
            )
    if report.excluded_currencies:
        lines.append(f"  (excluded currencies, no conversion: {', '.join(report.excluded_currencies)})")
    return "\n".join(lines)


def render_budget_status(status: BudgetStatus) -> str:
    if not status.lines:
        return f"No budgets configured for {status.period}."
    lines = [f"Budget status — {status.period} ({status.currency})"]
    for line in status.lines:
        lines.append(
            f"  - {line.category}: spent {format_minor(line.spent_minor, status.currency)}"
            f" of {format_minor(line.budget_minor, status.currency)}"
            f" ({'OVER by ' if line.overspent else 'left '}"
            f"{format_minor(abs(line.remaining_minor), status.currency)})"
        )
    lines.append(
        f"  Total: {format_minor(status.total_spent_minor, status.currency)}"
        f" of {format_minor(status.total_budget_minor, status.currency)}"
    )
    return "\n".join(lines)


def render_portfolio(summary: PortfolioSummary) -> str:
    if not summary.holdings:
        return "No holdings recorded."
    lines = [f"Portfolio ({summary.currency})"]
    for holding in summary.holdings:
        value = (
            format_minor(holding.market_value_minor, summary.currency)
            if holding.market_value_minor is not None
            else "no price"
        )
        pl = (
            format_minor(holding.unrealized_pl_minor, summary.currency)
            if holding.unrealized_pl_minor is not None
            else "-"
        )
        lines.append(
            f"  - {holding.symbol}: {_fmt_quantity(holding.quantity)} @ "
            f"{format_minor(holding.price_minor, summary.currency) if holding.price_minor is not None else '?'} "
            f"=> {value} (P/L {pl}, {holding.weight_pct * 100:.1f}%)"
        )
    lines.append(
        f"  Market value: {format_minor(summary.total_market_value_minor, summary.currency)} | "
        f"unrealized P/L: {format_minor(summary.total_unrealized_pl_minor, summary.currency)}"
    )
    return "\n".join(lines)


def render_goal(projection: GoalProjection) -> str:
    lines = [
        f"Goal '{projection.name}': {format_minor(projection.contributed_minor, projection.currency)}"
        f" of {format_minor(projection.target_minor, projection.currency)}"
        f" (remaining {format_minor(projection.remaining_minor, projection.currency)})"
    ]
    if projection.target_date is not None:
        lines.append(f"  Target date: {projection.target_date} ({projection.months_left} months left)")
    if projection.required_monthly_minor is not None:
        lines.append(
            f"  Required monthly: {format_minor(projection.required_monthly_minor, projection.currency)}"
        )
    if projection.months_to_target is not None:
        lines.append(f"  At the given rate: {projection.months_to_target} months to target")
    if projection.on_track is not None:
        lines.append(f"  On track: {'yes' if projection.on_track else 'no'}")
    return "\n".join(lines)


def chart_spec_for_report(report: SpendingReport, title: str | None = None) -> dict:
    """Build an apollo-charting spec (bar chart of spend by category)."""
    title = title or f"Spending {report.period_start} to {report.period_end}"
    data = [
        {
            "category": item.category,
            "amount": float(_major(item.amount_minor, report.currency)),
        }
        for item in report.by_category
    ] or [{"category": "No spend", "amount": 0.0}]
    return {
        "spec_version": 1,
        "chart": "bar",
        "title": title,
        "data": data,
        "x": {"key": "category"},
        "series": [{"key": "amount", "label": f"Spend ({report.currency})"}],
        "palette": "default",
        "legend": "bottom",
        "width": 720,
        "height": 420,
        "scale": 2,
    }


def pdf_spec_for_report(report: SpendingReport, title: str | None = None) -> dict:
    """Build an apollo-pdf-creator spec (report theme)."""
    title = title or f"Spending Report {report.period_start} to {report.period_end}"
    category_rows = [
        [item.category, format_minor(item.amount_minor, report.currency)]
        for item in report.by_category
    ]
    merchant_rows = [
        [m.merchant, format_minor(m.amount_minor, report.currency), str(m.count)]
        for m in report.top_merchants
    ]
    content: list[dict] = [
        {"type": "heading", "level": 1, "text": title},
        {
            "type": "paragraph",
            "text": (
                f"Period {report.period_start} to {report.period_end}. "
                f"Total spend {format_minor(report.total_spend_minor, report.currency)}; "
                f"income {format_minor(report.total_income_minor, report.currency)}; "
                f"net {format_minor(report.net_minor, report.currency)}."
            ),
        },
    ]
    if category_rows:
        content.append({"type": "heading", "level": 2, "text": "Spend by category"})
        content.append(
            {
                "type": "table",
                "header": ["Category", "Amount"],
                "zebra": True,
                "rows": category_rows,
            }
        )
    if merchant_rows:
        content.append({"type": "heading", "level": 2, "text": "Top merchants"})
        content.append(
            {
                "type": "table",
                "header": ["Merchant", "Amount", "Count"],
                "zebra": True,
                "rows": merchant_rows,
            }
        )
    return {
        "spec_version": 1,
        "meta": {"title": title, "author": "Artemis"},
        "theme": "report",
        "content": content,
    }
