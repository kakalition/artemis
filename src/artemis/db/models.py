"""SQLModel tables for Artemis.

Money is always stored as integer **minor units** (cents) plus an ISO-4217
currency code. No monetary column is ever a float.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Column, Index, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Owner(SQLModel, table=True):
    __tablename__ = "owners"

    id: str = Field(primary_key=True)
    name: str = "Owner"
    created_at: datetime = Field(default_factory=_utcnow)


class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    name: str
    kind: str = "checking"  # checking | savings | credit | cash | other
    currency: str = "USD"
    created_at: datetime = Field(default_factory=_utcnow)


class Category(SQLModel, table=True):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_category_owner_name"),)

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    name: str
    kind: str = "expense"  # expense | income | transfer
    created_at: datetime = Field(default_factory=_utcnow)


class MerchantRule(SQLModel, table=True):
    __tablename__ = "merchant_rules"

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    pattern: str = Field(index=True)
    category_id: int = Field(foreign_key="categories.id")
    priority: int = 100
    created_at: datetime = Field(default_factory=_utcnow)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_owner_posted", "owner_id", "posted_at"),
        Index("ix_tx_owner_external", "owner_id", "external_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    account_id: int | None = Field(default=None, foreign_key="accounts.id")
    posted_at: date = Field(index=True)
    amount_minor: int  # negative = spend, positive = income
    currency: str = "USD"
    description: str = ""
    merchant: str | None = None
    category_id: int | None = Field(default=None, foreign_key="categories.id")
    source: str = "manual"  # manual | import | llm
    external_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class Budget(SQLModel, table=True):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("owner_id", "category_id", "period", name="uq_budget_owner_cat_period"),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    category_id: int = Field(foreign_key="categories.id")
    period: str  # "YYYY-MM"
    amount_minor: int
    currency: str = "USD"
    created_at: datetime = Field(default_factory=_utcnow)


class Goal(SQLModel, table=True):
    __tablename__ = "goals"

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    name: str
    target_minor: int
    currency: str = "USD"
    target_date: date | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class GoalContribution(SQLModel, table=True):
    __tablename__ = "goal_contributions"

    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(index=True, foreign_key="goals.id")
    amount_minor: int
    currency: str = "USD"
    contributed_at: date = Field(default_factory=date.today)
    note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class Holding(SQLModel, table=True):
    __tablename__ = "holdings"

    id: int | None = Field(default=None, primary_key=True)
    owner_id: str = Field(index=True, foreign_key="owners.id")
    symbol: str = Field(index=True)
    quantity: Decimal = Field(sa_column=Column(Numeric(28, 10), nullable=False))
    cost_basis_minor: int = 0  # total cost basis in minor units
    currency: str = "USD"
    created_at: datetime = Field(default_factory=_utcnow)


class PriceSnapshot(SQLModel, table=True):
    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_price_symbol_asof", "symbol", "as_of"),)

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    as_of: date = Field(index=True)
    price_minor: int  # price per unit in minor units
    currency: str = "USD"
    source: str = "manual"  # manual | yfinance
    created_at: datetime = Field(default_factory=_utcnow)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(primary_key=True)  # e.g. "cli:default", "tg:12345"
    owner_id: str = Field(index=True, foreign_key="owners.id")
    channel: str = "cli"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_msg_conv_seq", "conversation_id", "seq"),)

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(index=True, foreign_key="conversations.id")
    seq: int = 0
    payload: str  # JSON-serialized ModelMessagesTypeAdapter payload
    created_at: datetime = Field(default_factory=_utcnow)


class A2ATaskRecord(SQLModel, table=True):
    """Optional durable record of A2A tasks (InMemory broker is the default)."""

    __tablename__ = "a2a_tasks"

    id: str = Field(primary_key=True)
    owner_id: str | None = Field(default=None, index=True)
    context_id: str | None = None
    state: str = "submitted"
    payload: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
