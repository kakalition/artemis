"""CLI backup/export and import-cap behavior (via CliRunner)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from artemis.cli import app
from artemis.config import get_settings


def _prepare(tmp_path, monkeypatch) -> CliRunner:
    monkeypatch.setenv("ARTEMIS_HOME", str(tmp_path / "home"))
    get_settings.cache_clear()
    return CliRunner()


def test_import_export_backup(tmp_path, monkeypatch):
    runner = _prepare(tmp_path, monkeypatch)

    result = runner.invoke(app, ["import", "tests/fixtures/sample.csv"])
    assert result.exit_code == 0, result.output

    dump = tmp_path / "transactions.json"
    result = runner.invoke(app, ["export", "--out", str(dump), "--format", "json"])
    assert result.exit_code == 0, result.output
    records = json.loads(dump.read_text())
    assert len(records) == 8

    csv_dump = tmp_path / "transactions.csv"
    result = runner.invoke(app, ["export", "--out", str(csv_dump), "--format", "csv"])
    assert result.exit_code == 0, result.output
    assert csv_dump.read_text().splitlines()[0].startswith("id,")

    backup = tmp_path / "backup.db"
    result = runner.invoke(app, ["backup", str(backup)])
    assert result.exit_code == 0, result.output
    assert backup.exists() and backup.stat().st_size > 0

    get_settings.cache_clear()


def test_up_with_nothing_enabled(tmp_path, monkeypatch):
    runner = _prepare(tmp_path, monkeypatch)
    result = runner.invoke(app, ["up", "--no-a2a", "--no-mcp", "--no-bot"])
    assert result.exit_code == 0, result.output
    assert "nothing to run" in result.output
    get_settings.cache_clear()


def test_workflows_empty_is_friendly(tmp_path, monkeypatch):
    runner = _prepare(tmp_path, monkeypatch)
    result = runner.invoke(app, ["workflows"])
    assert result.exit_code == 1
    assert "no durable workflows" in result.output
    get_settings.cache_clear()


def test_overlarge_import_fails(tmp_path, monkeypatch):
    runner = _prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("MAX_IMPORT_BYTES", "10")
    get_settings.cache_clear()
    result = runner.invoke(app, ["import", "tests/fixtures/sample.csv"])
    assert result.exit_code == 1
    assert "too large" in result.output
    get_settings.cache_clear()
