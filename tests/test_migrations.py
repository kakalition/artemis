"""Alembic migrations create the full schema."""

from __future__ import annotations

from sqlalchemy import inspect

from artemis.cli import _alembic_config
from artemis.config import get_settings
from artemis.db import create_db_engine


def test_alembic_upgrade_creates_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ARTEMIS_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    from alembic import command

    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    engine = create_db_engine(get_settings().resolved_database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "owners",
        "accounts",
        "categories",
        "merchant_rules",
        "transactions",
        "budgets",
        "goals",
        "goal_contributions",
        "holdings",
        "price_snapshots",
        "conversations",
        "messages",
        "a2a_tasks",
        "scheduled_jobs",
    } <= tables
    assert "alembic_version" in tables

    get_settings.cache_clear()
