"""Serializable tool response models.

Agents never return raw ORM rows or ``Decimal`` amounts to the model: these
models carry integer minor units plus a pre-formatted display string.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from artemis.db.models import Transaction
from artemis.domain.money import format_minor


class TransactionRecord(BaseModel):
    id: int
    posted_at: date
    amount_minor: int
    amount_display: str
    currency: str
    description: str
    merchant: str | None = None
    category: str | None = None

    @classmethod
    def from_model(cls, txn: Transaction, category_name: str | None = None) -> TransactionRecord:
        return cls(
            id=txn.id or 0,
            posted_at=txn.posted_at,
            amount_minor=txn.amount_minor,
            amount_display=format_minor(txn.amount_minor, txn.currency),
            currency=txn.currency,
            description=txn.description,
            merchant=txn.merchant,
            category=category_name,
        )


class ImportSummary(BaseModel):
    inserted: int
    skipped: int
    total_rows: int
    warnings: list[str] = Field(default_factory=list)
    source: str = "csv"


class CategoryRecord(BaseModel):
    id: int
    name: str
    kind: str


class BudgetRecord(BaseModel):
    category: str
    period: str
    amount_minor: int
    amount_display: str
    currency: str


class GoalRecord(BaseModel):
    id: int
    name: str
    target_minor: int
    target_display: str
    contributed_minor: int
    contributed_display: str
    remaining_minor: int
    currency: str
    target_date: date | None = None


class HoldingRecord(BaseModel):
    symbol: str
    quantity: Decimal
    cost_basis_minor: int
    price_minor: int | None = None
    market_value_minor: int | None = None
    unrealized_pl_minor: int | None = None
    currency: str = "USD"


class ArtifactRecord(BaseModel):
    kind: str  # "chart" | "pdf"
    path: str
    description: str = ""
