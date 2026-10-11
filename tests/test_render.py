from datetime import date
from decimal import Decimal

from artemis.domain.reports import (
    BudgetLine,
    BudgetStatus,
    CategoryTotal,
    HoldingLine,
    MerchantTotal,
    PortfolioSummary,
    SpendingReport,
)
from artemis.render import (
    chart_spec_for_report,
    pdf_spec_for_report,
    render_budget_status,
    render_portfolio,
    render_spending_report,
)


def _report() -> SpendingReport:
    return SpendingReport(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        currency="USD",
        total_spend_minor=13749,
        total_income_minor=250000,
        net_minor=236251,
        transaction_count=5,
        by_category=[
            CategoryTotal(category="Groceries", amount_minor=9450, share=Decimal("0.6874")),
            CategoryTotal(category="Dining", amount_minor=4299, share=Decimal("0.3126")),
        ],
        top_merchants=[MerchantTotal(merchant="Whole Foods", amount_minor=9450, count=2)],
        change_minor=-1000,
    )


def test_render_spending_report():
    text = render_spending_report(_report())
    assert "$137.49" in text
    assert "Groceries: $94.50" in text
    assert "Whole Foods" in text
    assert "vs previous period" in text


def test_chart_spec_for_report():
    spec = chart_spec_for_report(_report())
    assert spec["spec_version"] == 1
    assert spec["chart"] == "bar"
    assert {"category": "Groceries", "amount": 94.5} in spec["data"]
    assert spec["series"][0]["key"] == "amount"


def test_pdf_spec_for_report():
    spec = pdf_spec_for_report(_report())
    assert spec["spec_version"] == 1
    assert spec["theme"] == "report"
    assert spec["meta"]["title"].startswith("Spending Report")
    assert any(block.get("type") == "table" for block in spec["content"])


def test_render_budget_status():
    status = BudgetStatus(
        period="2026-01",
        currency="USD",
        lines=[
            BudgetLine(
                category_id=1,
                category="Groceries",
                budget_minor=8000,
                spent_minor=9450,
                remaining_minor=-1450,
                overspent=True,
                currency="USD",
            )
        ],
        total_budget_minor=8000,
        total_spent_minor=9450,
        total_remaining_minor=-1450,
    )
    text = render_budget_status(status)
    assert "OVER by $14.50" in text
    assert "Groceries" in text


def test_render_budget_status_empty():
    status = BudgetStatus(period="2026-01", currency="USD")
    assert "No budgets configured" in render_budget_status(status)


def test_render_portfolio():
    summary = PortfolioSummary(
        currency="USD",
        total_cost_basis_minor=30000,
        total_market_value_minor=32000,
        total_unrealized_pl_minor=2000,
        holdings=[
            HoldingLine(
                symbol="AAPL",
                quantity=Decimal("2"),
                cost_basis_minor=30000,
                price_minor=16000,
                market_value_minor=32000,
                unrealized_pl_minor=2000,
                weight_pct=Decimal("1.0000"),
                currency="USD",
            )
        ],
    )
    text = render_portfolio(summary)
    assert "AAPL: 2 @ $160.00" in text
    assert "→" in text or "=>" in text
    assert "P/L $20.00" in text
