from datetime import date
from decimal import Decimal

from artemis.db.models import Transaction


def test_category_get_or_create(repos):
    a = repos.categories.get_or_create("Groceries")
    b = repos.categories.get_or_create("groceries")
    assert a.id == b.id
    assert repos.categories.get_by_name("GROCERIES").id == a.id


def test_transaction_add_and_list(repos):
    groceries = repos.categories.get_or_create("Groceries")
    repos.transactions.add(
        posted_at=date(2026, 1, 5), amount_minor=-4250, merchant="Whole Foods", category_id=groceries.id
    )
    rows = repos.transactions.list()
    assert len(rows) == 1
    assert rows[0].amount_minor == -4250
    assert rows[0].currency == "USD"


def test_transaction_dedupe_by_external_id(repos):
    txns = [
        Transaction(
            owner_id="owner", posted_at=date(2026, 1, 5), amount_minor=-100,
            description="a", source="import", external_id="abc",
        ),
        Transaction(
            owner_id="owner", posted_at=date(2026, 1, 6), amount_minor=-200,
            description="b", source="import", external_id="abc",
        ),
        Transaction(
            owner_id="owner", posted_at=date(2026, 1, 7), amount_minor=-300,
            description="c", source="import", external_id="def",
        ),
    ]
    inserted, skipped = repos.transactions.bulk_add(txns)
    assert len(inserted) == 2
    assert skipped == 1

    more = [
        Transaction(
            owner_id="owner", posted_at=date(2026, 1, 7), amount_minor=-300,
            description="c", source="import", external_id="def",
        )
    ]
    inserted2, skipped2 = repos.transactions.bulk_add(more)
    assert inserted2 == []
    assert skipped2 == 1


def test_budget_upsert(repos):
    groceries = repos.categories.get_or_create("Groceries")
    b = repos.budgets.upsert(groceries.id, "2026-01", 50000)
    assert b.amount_minor == 50000
    b2 = repos.budgets.upsert(groceries.id, "2026-01", 60000)
    assert b2.id == b.id
    assert b2.amount_minor == 60000
    assert len(repos.budgets.list("2026-01")) == 1


def test_goal_contributions(repos):
    goal = repos.goals.create("Holiday", 200000, target_date=date(2026, 12, 1))
    repos.goals.add_contribution(goal.id, 50000, contributed_at=date(2026, 1, 15))
    repos.goals.add_contribution(goal.id, 25000, contributed_at=date(2026, 2, 15))
    assert repos.goals.contributed_minor(goal.id) == 75000
    assert len(repos.goals.contributions(goal.id)) == 2


def test_holdings_upsert(repos):
    h = repos.holdings.upsert("aapl", Decimal("1.5"), cost_basis_minor=9000)
    assert h.symbol == "AAPL"
    assert h.quantity == Decimal("1.5")
    h2 = repos.holdings.upsert("AAPL", Decimal("2"), cost_basis_minor=13000)
    assert h2.id == h.id
    assert h2.quantity == Decimal("2")
    assert len(repos.holdings.list()) == 1


def test_price_snapshot_latest(repos):
    repos.prices.add("AAPL", 15000, as_of=date(2026, 1, 1))
    repos.prices.add("AAPL", 16000, as_of=date(2026, 1, 2))
    latest = repos.prices.latest("AAPL")
    assert latest.price_minor == 16000
    assert len(repos.prices.history("aapl")) == 2


def test_conversation_and_messages(repos):
    repos.conversations.get_or_create("cli:default", channel="cli")
    repos.messages.append("cli:default", ['{"a": 1}', '{"b": 2}'])
    assert repos.messages.next_seq("cli:default") == 2
    stored = repos.messages.list("cli:default")
    assert [m.seq for m in stored] == [0, 1]
    repos.messages.clear("cli:default")
    assert repos.messages.list("cli:default") == []
