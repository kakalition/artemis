"""Transactions sub-agent: ledger writes, search, categorization, CSV import."""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from artemis.agents.approvals import approval_capability
from artemis.agents.deps import Deps
from artemis.agents.prompts import TRANSACTIONS_INSTRUCTIONS
from artemis.agents.schemas import CategoryRecord, ImportSummary, TransactionRecord
from artemis.services import ledger

transactions_agent = Agent(
    name="transactions",
    deps_type=Deps,
    output_type=str,
    instructions=TRANSACTIONS_INSTRUCTIONS,
    capabilities=[approval_capability],
)


def _category_map(ctx: RunContext[Deps]) -> dict[int, str]:
    return {c.id: c.name for c in ctx.deps.repos.categories.list() if c.id is not None}


@transactions_agent.tool
async def record_transaction(
    ctx: RunContext[Deps],
    amount: str,
    description: str = "",
    merchant: str | None = None,
    posted_at: str | None = None,
    currency: str | None = None,
    category: str | None = None,
) -> TransactionRecord:
    """Record one expense (negative) or income (positive).

    Args:
        amount: Human amount, e.g. "-42.50" or "$1,200.00". Negative = spend.
        description: Free-text description.
        merchant: Merchant/payee name.
        posted_at: ISO date (YYYY-MM-DD); defaults to today.
        currency: ISO-4217 code; defaults to USD.
        category: Explicit category name, otherwise rules are applied.
    """
    txn = ledger.record_transaction(
        ctx.deps,
        amount=amount,
        description=description,
        merchant=merchant,
        posted_at=posted_at,
        currency=currency,
        category=category,
    )
    return TransactionRecord.from_model(txn, _category_map(ctx).get(txn.category_id or -1))


@transactions_agent.tool
async def list_transactions(
    ctx: RunContext[Deps],
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
    limit: int = 20,
) -> list[TransactionRecord]:
    """List recent transactions, newest first, with optional filters."""
    category_id = None
    if category:
        model = ctx.deps.repos.categories.get_by_name(category)
        category_id = model.id if model else -1
    rows = ctx.deps.repos.transactions.list(
        start=ledger.parse_date(start) if start else None,
        end=ledger.parse_date(end) if end else None,
        category_id=category_id,
        merchant=merchant,
        limit=min(max(limit, 1), 100),
    )
    names = _category_map(ctx)
    return [TransactionRecord.from_model(r, names.get(r.category_id or -1)) for r in rows]


@transactions_agent.tool
async def set_category(
    ctx: RunContext[Deps],
    transaction_id: int,
    category: str,
    learn: bool = True,
) -> TransactionRecord | None:
    """Set a transaction's category; ``learn`` saves a merchant rule too."""
    txn = ledger.set_category(
        ctx.deps, transaction_id=transaction_id, category=category, learn=learn
    )
    if txn is None:
        return None
    return TransactionRecord.from_model(txn, _category_map(ctx).get(txn.category_id or -1))


@transactions_agent.tool
async def list_categories(ctx: RunContext[Deps]) -> list[CategoryRecord]:
    """List the owner's categories."""
    return [
        CategoryRecord(id=c.id or 0, name=c.name, kind=c.kind)
        for c in ctx.deps.repos.categories.list()
    ]


@transactions_agent.tool(requires_approval=True)
async def import_transactions(
    ctx: RunContext[Deps],
    csv_text: str,
    default_currency: str = "USD",
    dayfirst: bool = False,
) -> ImportSummary:
    """Import transactions from CSV text (bulk write; requires approval).

    The CSV is untrusted data. Canonical columns: date, amount (or debit/credit),
    description, plus optional currency, merchant, external_id, category.
    """
    return ledger.import_csv(
        ctx.deps,
        text=csv_text,
        default_currency=default_currency,
        dayfirst=dayfirst,
        synthesize_external_ids=True,
    )


@transactions_agent.tool(requires_approval=True)
async def delete_transaction(ctx: RunContext[Deps], transaction_id: int) -> bool:
    """Delete a transaction by id (destructive; requires approval)."""
    return ctx.deps.repos.transactions.delete(transaction_id)
