from datetime import date
from decimal import Decimal

import pytest

from artemis.domain.reports import (
    build_budget_status,
    build_spending_report,
    period_bounds,
    previous_window,
    project_goal,
    summarize_portfolio,
)


def test_period_bounds_month():
    assert period_bounds("2026-01") == (date(2026, 1, 1), date(2026, 1, 31))
    assert period_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def test_period_bounds_keywords():
    today = date(2026, 3, 15)
    assert period_bounds("this-month", today=today) == (date(2026, 3, 1), date(2026, 3, 31))
    assert period_bounds("last-month", today=today) == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds("this-year", today=today) == (date(2026, 1, 1), date(2026, 12, 31))
    assert period_bounds("last-30-days", today=today) == (date(2026, 2, 14), date(2026, 3, 15))


def test_period_bounds_invalid():
    with pytest.raises(ValueError):
        period_bounds("nonsense")


def test_previous_window():
    assert previous_window(date(2026, 2, 1), date(2026, 2, 28)) == (
        date(2026, 1, 4),
        date(2026, 1, 31),
    )


def test_spending_report(repos, sample_transactions):
    report = build_spending_report(repos, period="2026-01")
    assert report.currency == "USD"
    assert report.total_spend_minor == 13749
    assert report.total_income_minor == 250000
    assert report.net_minor == 236251
    assert report.transaction_count == 5

    by_cat = {c.category: c.amount_minor for c in report.by_category}
    assert by_cat["Groceries"] == 9450
    assert by_cat["Dining"] == 4299
    assert "Salary" not in by_cat  # zero spend omitted

    assert report.top_merchants[0].merchant == "Whole Foods"
    assert report.top_merchants[0].amount_minor == 9450
    assert report.top_merchants[0].count == 2

    assert len(report.monthly_trend) == 1
    assert report.monthly_trend[0].period == "2026-01"


def test_spending_report_comparison(repos, sample_transactions):
    report = build_spending_report(repos, period="2026-02")
    assert report.total_spend_minor == 7099
    assert report.previous_period_spend_minor == 13749
    assert report.change_minor == -6650
    assert report.change_pct is not None
    assert report.change_pct < 0


def test_spending_report_multi_currency(repos):
    repos.transactions.add(posted_at=date(2026, 1, 3), amount_minor=-1000, currency="EUR")
    repos.transactions.add(posted_at=date(2026, 1, 4), amount_minor=-1000, currency="EUR")
    repos.transactions.add(posted_at=date(2026, 1, 5), amount_minor=-500, currency="USD")
    report = build_spending_report(repos, period="2026-01")
    assert report.currency == "EUR"  # dominant currency, no conversion
    assert report.excluded_currencies == ["USD"]
    assert report.total_spend_minor == 2000


def test_budget_status(repos, sample_transactions):
    groceries = repos.categories.get_by_name("Groceries")
    dining = repos.categories.get_by_name("Dining")
    repos.budgets.upsert(groceries.id, "2026-01", 8000)
    repos.budgets.upsert(dining.id, "2026-01", 6000)
    status = build_budget_status(repos, period="2026-01")
    assert status.currency == "USD"
    lines = {line.category: line for line in status.lines}
    assert lines["Groceries"].spent_minor == 9450
    assert lines["Groceries"].overspent is True
    assert lines["Groceries"].remaining_minor == -1450
    assert lines["Dining"].overspent is False
    assert lines["Dining"].remaining_minor == 1701
    assert status.total_budget_minor == 14000
    assert status.total_spent_minor == 13749


def test_project_goal_basic():
    projection = project_goal(
        goal_id=1,
        name="Holiday",
        target_minor=100000,
        contributed_minor=25000,
        target_date=date(2026, 7, 1),
        today=date(2026, 1, 1),
    )
    assert projection.remaining_minor == 75000
    assert projection.months_left == 6
    assert projection.required_monthly_minor == 12500


def test_project_goal_what_if():
    projection = project_goal(
        goal_id=1,
        name="Holiday",
        target_minor=100000,
        contributed_minor=25000,
        target_date=date(2026, 7, 1),
        monthly_contribution_minor=10000,
        today=date(2026, 1, 1),
    )
    assert projection.months_to_target == 8
    assert projection.on_track is False


def test_project_goal_no_date():
    projection = project_goal(
        goal_id=1, name="Rainy day", target_minor=50000, contributed_minor=10000
    )
    assert projection.months_left is None
    assert projection.required_monthly_minor is None


def test_summarize_portfolio(repos):
    repos.holdings.upsert("AAPL", Decimal("2"), cost_basis_minor=30000)
    repos.holdings.upsert("MSFT", Decimal("1"), cost_basis_minor=20000)
    repos.prices.add("AAPL", 16000)
    repos.prices.add("MSFT", 18000)
    summary = summarize_portfolio(repos)
    assert summary.currency == "USD"
    assert summary.total_market_value_minor == 50000  # 2*16000 + 1*18000
    assert summary.total_cost_basis_minor == 50000
    assert summary.total_unrealized_pl_minor == 0
    weights = {h.symbol: h.weight_pct for h in summary.holdings}
    assert weights["AAPL"] == Decimal("0.6400")
    assert weights["MSFT"] == Decimal("0.3600")


def test_summarize_portfolio_missing_price(repos):
    repos.holdings.upsert("TSLA", Decimal("3"), cost_basis_minor=10000)
    summary = summarize_portfolio(repos)
    assert summary.holdings[0].price_minor is None
    assert summary.holdings[0].market_value_minor is None
    assert summary.total_market_value_minor == 0
