from collections.abc import Iterator
from datetime import date

import pytest
from sqlmodel import Session

from artemis.db import create_db_engine
from artemis.db.migrations import bootstrap
from artemis.db.repos import Repositories


@pytest.fixture
def repos(tmp_path) -> Iterator[Repositories]:
    db_file = tmp_path / "artemis.db"
    engine = create_db_engine(f"sqlite+libsql:///{db_file}")
    bootstrap(engine, owner_id="owner", owner_name="Owner")
    with Session(engine) as session:
        yield Repositories(session, "owner")
        session.rollback()


@pytest.fixture
def sample_transactions(repos: Repositories):
    account = repos.accounts.get_or_create_default()
    groceries = repos.categories.get_or_create("Groceries")
    dining = repos.categories.get_or_create("Dining")
    salary = repos.categories.get_or_create("Salary", kind="income")
    rows = [
        dict(posted_at=date(2026, 1, 5), amount_minor=-4250, merchant="Whole Foods", category_id=groceries.id, description="Weekly shop"),
        dict(posted_at=date(2026, 1, 12), amount_minor=-5200, merchant="Whole Foods", category_id=groceries.id, description="Weekly shop"),
        dict(posted_at=date(2026, 1, 8), amount_minor=-1899, merchant="Cafe Rio", category_id=dining.id, description="Lunch"),
        dict(posted_at=date(2026, 1, 15), amount_minor=-2400, merchant="Cafe Rio", category_id=dining.id, description="Lunch"),
        dict(posted_at=date(2026, 1, 1), amount_minor=250000, merchant="Acme", category_id=salary.id, description="Paycheck", source="manual"),
        dict(posted_at=date(2026, 2, 2), amount_minor=-6100, merchant="Whole Foods", category_id=groceries.id, description="Weekly shop"),
        dict(posted_at=date(2026, 2, 3), amount_minor=-999, merchant="Cafe Rio", category_id=dining.id, description="Lunch"),
    ]
    for row in rows:
        row.setdefault("account_id", account.id)
        repos.transactions.add(**row)
    repos.session.flush()
    return rows
