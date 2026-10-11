"""Schema creation and seeding.

libSQL is SQLite-compatible, so ``create_all`` is sufficient for v1. A real
migration runner (alembic) can be layered on later behind this module.
"""

from __future__ import annotations

from agentkit.db.migrations import sync_missing_columns
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, select

from artemis.db.models import Category, Owner

DEFAULT_EXPENSE_CATEGORIES = [
    "Groceries",
    "Dining",
    "Transport",
    "Housing",
    "Utilities",
    "Health",
    "Entertainment",
    "Shopping",
    "Travel",
    "Education",
    "Subscriptions",
    "Fees",
    "Other",
]
DEFAULT_INCOME_CATEGORIES = ["Salary", "Interest", "Gifts", "Refunds", "Income"]


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist, and reconcile additive drift."""
    SQLModel.metadata.create_all(engine)
    sync_missing_columns(engine)


def seed_owner(session: Session, owner_id: str, owner_name: str = "Owner") -> Owner:
    """Ensure the single owner row exists and return it."""
    existing = session.get(Owner, owner_id)
    if existing is not None:
        return existing
    owner = Owner(id=owner_id, name=owner_name)
    session.add(owner)
    session.flush()
    return owner


def seed_default_categories(session: Session, owner_id: str) -> None:
    """Create the default category set for an owner if absent."""
    existing = set(session.exec(select(Category.name).where(Category.owner_id == owner_id)).all())
    for name in DEFAULT_EXPENSE_CATEGORIES:
        if name not in existing:
            session.add(Category(owner_id=owner_id, name=name, kind="expense"))
    for name in DEFAULT_INCOME_CATEGORIES:
        if name not in existing:
            session.add(Category(owner_id=owner_id, name=name, kind="income"))
    session.flush()


def bootstrap(engine: Engine, owner_id: str, owner_name: str = "Owner") -> None:
    """Create the schema, the owner row, and default categories."""
    init_db(engine)
    from sqlmodel import Session as _Session

    with _Session(engine) as session:
        seed_owner(session, owner_id, owner_name)
        seed_default_categories(session, owner_id)
        session.commit()
