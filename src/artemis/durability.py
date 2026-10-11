"""Durable execution built on **DBOS Transact**.

DBOS gives lightweight durable workflows/queues/schedules backed by a local
SQLite *system database* (``$ARTEMIS_HOME/dbos.sqlite``) — no separate server,
unlike Temporal. Agent turns, report jobs and scheduled automations are
checkpointed, so they resume/retry across process restarts instead of being
lost.

The workflow bodies are deterministic; every side effect (LLM call, DB write,
artifact render) is a ``@DBOS.step`` so it is recorded and never repeated once
it has completed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from agentkit import durability as _durability
from agentkit import scheduler
from agentkit.durability import (  # noqa: F401  (re-exported DBOS surface)
    cancel_workflow,
    client,
    get_workflow,
    list_workflows,
    resume_workflow,
    sleep,
)
from dbos import DBOS, SetWorkflowID

from artemis.config import Settings, build_model, get_settings, model_settings, usage_limits
from artemis.domain.reports import SpendingReport, build_spending_report
from artemis.mcp.registry import MCPRegistry, extract_metadata_blocks
from artemis.render import chart_spec_for_report, pdf_spec_for_report, render_spending_report
from artemis.services.runtime import build_deps, build_runtime, repositories
from artemis.services.session import load_history, serialize_message

REPORT_QUEUE = "artemis"

_model_factory: Callable[[Settings], Any] | None = None


def set_model_factory(factory: Callable[[Settings], Any] | None) -> None:
    """Override how the model is built inside steps (used by tests)."""
    global _model_factory
    _model_factory = factory


def _build_model(settings: Settings) -> Any:
    return _model_factory(settings) if _model_factory is not None else build_model(settings)


def init(settings: Settings | None = None, *, launch: bool = True) -> type[DBOS]:
    """Configure and launch DBOS once per process (via agentkit)."""
    return _durability.init(settings or get_settings(), launch=launch, queues=[REPORT_QUEUE])


# --------------------------------------------------------------------------
# Durable agent turn
# --------------------------------------------------------------------------


@DBOS.step(retries_allowed=True, max_attempts=3, backoff_rate=2.0)
def _step_run_agent(conversation_id: str, text: str) -> dict[str, Any]:
    settings = get_settings()
    runtime = build_runtime(settings)
    with repositories(runtime) as repos:
        channel = conversation_id.split(":", 1)[0]
        repos.conversations.get_or_create(conversation_id, channel=channel)
        history = load_history(repos, conversation_id)
        deps = build_deps(runtime, repos, model=_build_model(settings))
        from artemis.agents.orchestrator import orchestrator_agent

        result = asyncio.run(
            orchestrator_agent.run(
                text,
                deps=deps,
                message_history=history,
                model=deps.model,
                model_settings=model_settings(settings),
                usage_limits=usage_limits(settings),
            )
        )
        all_messages = result.all_messages()
        new_payloads = [serialize_message(m) for m in all_messages[len(history):]]
        repos.conversations.touch(conversation_id)
    return {
        "output": result.output if isinstance(result.output, str) else str(result.output),
        "artifacts": list(deps.artifacts),
        "new_payloads": new_payloads,
    }


@DBOS.step()
def _step_persist(conversation_id: str, new_payloads: list[str]) -> int:
    if not new_payloads:
        return 0
    runtime = build_runtime(get_settings())
    with repositories(runtime) as repos:
        existing = [m.payload for m in repos.messages.list(conversation_id)]
        # Idempotent on replay: skip if this exact tail is already stored.
        if existing and existing[-len(new_payloads):] == new_payloads:
            return 0
        return repos.messages.append(conversation_id, new_payloads)


@DBOS.workflow()
def agent_turn(conversation_id: str, text: str) -> dict[str, Any]:
    """A durable agent turn: run + persist, resumable across restarts."""
    run = _step_run_agent(conversation_id, text)
    _step_persist(conversation_id, run["new_payloads"])
    return {"output": run["output"], "artifacts": run["artifacts"]}


def run_turn(
    text: str,
    *,
    conversation_id: str = "cli:default",
    workflow_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run a durable agent turn and wait for its result."""
    init(settings)
    if workflow_id:
        with SetWorkflowID(workflow_id):
            handle = DBOS.start_workflow(agent_turn, conversation_id, text)
    else:
        handle = DBOS.start_workflow(agent_turn, conversation_id, text)
    return handle.get_result()


def enqueue_turn(
    text: str, *, conversation_id: str = "cli:default", settings: Settings | None = None
) -> str:
    """Enqueue a durable agent turn on the background queue; returns the workflow id."""
    init(settings)
    return _durability.enqueue(REPORT_QUEUE, agent_turn, conversation_id, text)


# --------------------------------------------------------------------------
# Durable report job
# --------------------------------------------------------------------------


def _first_out(result: Any) -> str | None:
    data = getattr(result, "data", None)
    if isinstance(data, dict) and (data.get("out") or data.get("path")):
        return str(data.get("out") or data.get("path"))
    for block in extract_metadata_blocks(result):
        found = block.get("out") or block.get("path")
        if found:
            return str(found)
    return None


@DBOS.step()
def _step_build_report(period: str, currency: str | None) -> str:
    runtime = build_runtime(get_settings())
    with repositories(runtime) as repos:
        report = build_spending_report(repos, period=period, currency=currency)
    return report.model_dump_json()


@DBOS.step(retries_allowed=True, max_attempts=2)
def _step_render_artifacts(report_json: str, chart: bool, pdf: bool) -> list[dict[str, Any]]:
    report = SpendingReport.model_validate_json(report_json)

    async def _go() -> list[dict[str, Any]]:
        registry = MCPRegistry(get_settings())
        rendered: list[dict[str, Any]] = []
        async with registry:
            if chart:
                result = await registry.call_tool(
                    "chart", "render_chart", {"spec": chart_spec_for_report(report), "force": True}
                )
                rendered.append({"kind": "chart", "path": _first_out(result)})
            if pdf:
                result = await registry.call_tool(
                    "pdf", "create_pdf", {"spec": pdf_spec_for_report(report), "force": True}
                )
                rendered.append({"kind": "pdf", "path": _first_out(result)})
        return rendered

    return asyncio.run(_go())


@DBOS.workflow()
def report_job(period: str, currency: str | None = None, chart: bool = False, pdf: bool = False) -> dict[str, Any]:
    """A durable spending-report job (text, plus optional chart/PDF artifacts)."""
    report_json = _step_build_report(period, currency)
    report = SpendingReport.model_validate_json(report_json)
    artifacts = _step_render_artifacts(report_json, chart, pdf) if (chart or pdf) else []
    return {
        "text": render_spending_report(report),
        "artifacts": artifacts,
    }


def run_report_job(
    period: str = "this-month",
    *,
    currency: str | None = None,
    chart: bool = False,
    pdf: bool = False,
    workflow_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    init(settings)
    if workflow_id:
        with SetWorkflowID(workflow_id):
            handle = DBOS.start_workflow(report_job, period, currency, chart, pdf)
    else:
        handle = DBOS.start_workflow(report_job, period, currency, chart, pdf)
    return handle.get_result()


def enqueue_report_job(
    period: str = "this-month",
    *,
    currency: str | None = None,
    chart: bool = False,
    pdf: bool = False,
    settings: Settings | None = None,
) -> str:
    """Queue a durable report job on the background worker; returns its id."""
    init(settings)
    return _durability.enqueue(REPORT_QUEUE, report_job, period, currency, chart, pdf)


# --------------------------------------------------------------------------
# Scheduling (agentkit.scheduler): cron + one-off
# --------------------------------------------------------------------------


@scheduler.task("report")
def _report_task(
    period: str = "last-month", chart: bool = False, pdf: bool = False
) -> None:
    """Registered scheduler task: run a durable spending-report job."""
    run_report_job(period, chart=chart, pdf=pdf)


def schedule_report(
    *,
    name: str,
    period: str = "last-month",
    chart: bool = False,
    pdf: bool = False,
    cron: str | None = None,
    at: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Schedule a recurring (``cron``) or one-off (``at`` ISO datetime) report."""
    settings = settings or get_settings()
    scheduler.configure(settings)
    args = {"period": period, "chart": chart, "pdf": pdf}
    if cron:
        scheduler.schedule_cron(name, cron, "report", args=args)
    elif at:
        scheduler.schedule_once(name, at, "report", args=args)
    else:
        raise ValueError("provide either cron= or at=")


def list_report_schedules() -> list[dict[str, Any]]:
    scheduler.configure(get_settings())
    return scheduler.list_jobs()


def remove_report_schedule(name: str) -> bool:
    scheduler.configure(get_settings())
    return scheduler.remove_job(name)
