"""High-level ledger operations used by agent tools.

Pure orchestration over repositories + domain helpers. No LLM calls live here;
the LLM fallback for categorization happens in the agent, which calls back into
:func:`set_category` with ``learn=True``.
"""

from __future__ import annotations

from datetime import date

from artemis.agents.deps import Deps
from artemis.agents.schemas import ImportSummary
from artemis.db.models import Category, Transaction
from artemis.domain.categorizer import normalize_merchant, rule_from_merchant
from artemis.domain.dates import parse_date
from artemis.domain.imports import parse_csv
from artemis.domain.money import parse_amount

__all__ = [
    "parse_date",
    "resolve_category",
    "apply_rules",
    "record_transaction",
    "set_category",
    "import_csv",
]


def resolve_category(deps: Deps, name: str | None, kind: str = "expense") -> Category | None:
    if not name:
        return None
    repo = deps.repos.categories
    existing = repo.get_by_name(name)
    if existing:
        return existing
    return repo.create(name, kind=kind)


def apply_rules(deps: Deps, merchant: str | None, description: str | None) -> Category | None:
    text = f"{merchant or ''} {description or ''}"
    rules = deps.repos.rules.list()
    by_id = {c.id: c for c in deps.repos.categories.list() if c.id is not None}
    from artemis.domain.categorizer import match_rule

    match = match_rule(text, rules, by_id)
    if match.category_id is None:
        return None
    return by_id.get(match.category_id)


def record_transaction(
    deps: Deps,
    *,
    amount: str | int,
    description: str = "",
    merchant: str | None = None,
    posted_at: str | date | None = None,
    currency: str | None = None,
    category: str | None = None,
    source: str = "manual",
    external_id: str | None = None,
) -> Transaction:
    """Record one transaction. ``amount`` is a human string (or int minor units)."""
    currency = (currency or "USD").upper()
    amount_minor = amount if isinstance(amount, int) else parse_amount(amount, currency)

    normalized_merchant = normalize_merchant(merchant)
    resolved = resolve_category(deps, category)
    if resolved is None and category is None:
        resolved = apply_rules(deps, normalized_merchant, description)

    account = deps.repos.accounts.get_or_create_default(currency=currency)
    return deps.repos.transactions.add(
        posted_at=parse_date(posted_at),
        amount_minor=amount_minor,
        currency=currency,
        description=description,
        merchant=normalized_merchant,
        category_id=resolved.id if resolved else None,
        account_id=account.id,
        source=source,
        external_id=external_id,
    )


def set_category(
    deps: Deps,
    *,
    transaction_id: int,
    category: str,
    learn: bool = False,
) -> Transaction | None:
    """Set a transaction's category, optionally persisting a merchant rule."""
    category_model = resolve_category(deps, category)
    if category_model is None or category_model.id is None:
        return None
    txn = deps.repos.transactions.set_category(transaction_id, category_model.id)
    if txn is not None and learn:
        pattern = rule_from_merchant(txn.merchant, txn.description)
        if pattern:
            existing = {r.pattern for r in deps.repos.rules.list()}
            if pattern not in existing:
                deps.repos.rules.add(pattern, category_model.id)
    return txn


def import_csv(
    deps: Deps,
    *,
    text: str,
    default_currency: str = "USD",
    dayfirst: bool = False,
    synthesize_external_ids: bool = True,
    account_name: str | None = None,
) -> ImportSummary:
    """Parse CSV text and insert new, deduplicated transactions."""
    size = len(text.encode("utf-8"))
    if size > deps.settings.max_import_bytes:
        raise ValueError(
            f"CSV is too large ({size} bytes > {deps.settings.max_import_bytes} limit)"
        )
    result = parse_csv(
        text,
        default_currency=default_currency,
        dayfirst=dayfirst,
        synthesize_external_ids=synthesize_external_ids,
    )
    account = deps.repos.accounts.get_or_create_default(currency=default_currency)
    rows: list[Transaction] = []
    categories = {c.name.lower(): c for c in deps.repos.categories.list()}
    by_id = {c.id: c for c in deps.repos.categories.list() if c.id is not None}
    for parsed in result.rows:
        category_id = None
        if parsed.category_name:
            category = categories.get(parsed.category_name.lower())
            if category is None:
                category = deps.repos.categories.create(parsed.category_name)
                categories[parsed.category_name.lower()] = category
            category_id = category.id
        else:
            from artemis.domain.categorizer import match_rule

            match = match_rule(
                f"{parsed.merchant or ''} {parsed.description}", deps.repos.rules.list(), by_id
            )
            category_id = match.category_id
        rows.append(
            Transaction(
                owner_id=deps.owner_id,
                account_id=account.id,
                posted_at=parsed.posted_at,
                amount_minor=parsed.amount_minor,
                currency=parsed.currency,
                description=parsed.description,
                merchant=parsed.merchant,
                category_id=category_id,
                source="import",
                external_id=parsed.external_id,
            )
        )
    inserted, skipped = deps.repos.transactions.bulk_add(rows)
    return ImportSummary(
        inserted=len(inserted),
        skipped=skipped,
        total_rows=len(result.rows),
        warnings=result.warnings,
        source="csv",
    )
