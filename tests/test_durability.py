"""Durable execution tests (DBOS on a local SQLite system database).

DBOS is process-global, so the whole module shares one temp ARTEMIS_HOME.
"""

from __future__ import annotations

import os

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

import artemis.config as config


@pytest.fixture(scope="module")
def durability(tmp_path_factory):
    home = tmp_path_factory.mktemp("durable")
    previous = os.environ.get("ARTEMIS_HOME")
    os.environ["ARTEMIS_HOME"] = str(home)
    config.get_settings.cache_clear()

    from artemis import durability as module

    module.set_model_factory(
        lambda s: FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("durable reply")]))
    )
    yield module

    module.set_model_factory(None)
    if previous is None:
        os.environ.pop("ARTEMIS_HOME", None)
    else:
        os.environ["ARTEMIS_HOME"] = previous
    config.get_settings.cache_clear()


def test_durable_turn_runs_and_persists(durability):
    first = durability.run_turn("hello", conversation_id="cli:durable-test")
    assert first["output"] == "durable reply"

    # A second turn reuses the persisted history (durable, no loss).
    second = durability.run_turn("more", conversation_id="cli:durable-test")
    assert second["output"] == "durable reply"

    runtime = durability.build_runtime(durability.get_settings())
    with durability.repositories(runtime) as repos:
        assert repos.messages.list("cli:durable-test")


def test_durable_report_job(durability):
    result = durability.run_report_job("this-month")
    assert "Spending report" in result["text"]


def test_durable_cron_schedule(durability):
    durability.schedule_report(name="weekly-test", cron="0 8 * * 1", period="last-month")
    jobs = {job["name"]: job for job in durability.list_report_schedules()}
    assert jobs["weekly-test"]["kind"] == "cron"
    assert jobs["weekly-test"]["task"] == "report"


def test_durable_one_off_schedule(durability):
    durability.schedule_report(name="once-test", at="2026-12-01T09:00", period="last-month")
    jobs = {job["name"]: job for job in durability.list_report_schedules()}
    assert jobs["once-test"]["kind"] == "once"
    assert jobs["once-test"]["schedule"].startswith("2026-12-01T09:00")
    assert durability.remove_report_schedule("once-test") is True
