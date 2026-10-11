"""Typer CLI for Artemis."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

import typer

from artemis import __version__
from artemis.agents.deps import ApprovalRequest
from artemis.config import build_model, get_settings
from artemis.domain.reports import (
    build_budget_status,
    build_spending_report,
    summarize_portfolio,
)
from artemis.mcp.registry import MCPRegistry, extract_metadata_blocks
from artemis.render import (
    chart_spec_for_report,
    pdf_spec_for_report,
    render_budget_status,
    render_portfolio,
    render_spending_report,
)
from artemis.services import ledger
from artemis.services.runtime import build_deps, build_runtime, repositories
from artemis.services.session import ChatRunner

app = typer.Typer(
    add_completion=False,
    help="Artemis — a personal finance agent (CLI + Telegram, MCP + A2A).",
    no_args_is_help=True,
)


def _first_out(result: object) -> str | None:
    data = getattr(result, "data", None)
    if isinstance(data, dict) and (data.get("out") or data.get("path")):
        return str(data.get("out") or data.get("path"))
    for block in extract_metadata_blocks(result):
        out = block.get("out") or block.get("path")
        if out:
            return str(out)
    return None


async def _cli_approver(requests: list[ApprovalRequest]) -> dict[str, bool]:
    decisions: dict[str, bool] = {}
    for request in requests:
        typer.echo(f"⚠  Approve {request.tool_name} with args {request.args}?")
        answer = await asyncio.to_thread(typer.prompt, "  [y/N]", default="n")
        decisions[request.tool_call_id] = answer.strip().lower() in {"y", "yes"}
    return decisions


async def _render_artifacts(
    registry: MCPRegistry, report, want_chart: bool, want_pdf: bool, out_dir: Path | None
) -> None:
    if want_chart:
        result = await registry.call_tool(
            "chart", "render_chart", {"spec": chart_spec_for_report(report), "force": True}
        )
        typer.echo(f"chart: {_maybe_copy(_first_out(result), out_dir)}")
    if want_pdf:
        result = await registry.call_tool(
            "pdf", "create_pdf", {"spec": pdf_spec_for_report(report), "force": True}
        )
        typer.echo(f"pdf: {_maybe_copy(_first_out(result), out_dir)}")


def _maybe_copy(path: str | None, out_dir: Path | None) -> str | None:
    if not path or out_dir is None:
        return path
    src = Path(path)
    if not src.exists():
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / src.name
    shutil.copy2(src, dest)
    return str(dest)


def asyncio_run(coro):
    return asyncio.run(coro)


@app.command()
def version() -> None:
    """Print the Artemis version."""
    typer.echo(f"artemis {__version__}")


db_app = typer.Typer(no_args_is_help=True, help="Database migrations (Alembic).")
app.add_typer(db_app, name="db")


def _alembic_config():
    from alembic.config import Config as AlembicConfig

    root = Path(__file__).resolve().parents[2]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().resolved_database_url)
    return cfg


@db_app.command("upgrade")
def db_upgrade(revision: str = typer.Argument("head")) -> None:
    """Apply migrations up to REVISION (default: head)."""
    from alembic import command

    command.upgrade(_alembic_config(), revision)
    typer.echo(f"database migrated to {revision}")


@db_app.command("current")
def db_current() -> None:
    """Show the current migration revision."""
    from alembic import command

    command.current(_alembic_config())


@db_app.command("revision")
def db_revision(message: str = typer.Option(..., "-m", "--message")) -> None:
    """Autogenerate a new migration from the current models."""
    from alembic import command

    command.revision(_alembic_config(), message=message, autogenerate=True)
    typer.echo("revision created")


@app.command()
def soul(
    init: bool = typer.Option(False, "--init", help="Write a default SOUL.md if missing."),
) -> None:
    """Show the active SOUL.md persona (or scaffold one with --init)."""
    from artemis.soul import ensure_soul, load_soul, resolve_soul_path

    settings = get_settings()
    if init:
        path = ensure_soul(settings)
        typer.echo(f"wrote {path}")
        return
    typer.echo(f"# {resolve_soul_path(settings)}")
    typer.echo(load_soul(settings))


@app.command()
def chat(
    conv: str = typer.Option("cli:default", help="Conversation id."),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Do not connect to the apollo MCP servers."),
) -> None:
    """Interactive chat with the finance agent."""
    asyncio_run(_chat(conv, with_mcp=not no_mcp))


async def _chat(conv: str, with_mcp: bool) -> None:
    _enable_observability()
    runtime = build_runtime()
    registry = MCPRegistry(runtime.settings) if with_mcp else None
    async with contextlib.AsyncExitStack() as stack:
        if registry is not None:
            await stack.enter_async_context(registry)
            if registry.errors:
                typer.echo(f"(mcp: {registry.errors})", err=True)
        from artemis.a2a.client import build_a2a_client

        with repositories(runtime) as repos:
            deps = build_deps(
                runtime,
                repos,
                model=build_model(runtime.settings),
                mcp=registry,
                a2a=build_a2a_client(runtime.settings),
                approve=_cli_approver,
            )
            runner = ChatRunner(deps, conversation_id=conv)
            typer.echo(f"Artemis chat ({conv}). Type 'exit' to quit.")
            while True:
                try:
                    text = await asyncio.to_thread(input, "you> ")
                except (EOFError, KeyboardInterrupt):
                    break
                text = text.strip()
                if text in {"exit", "quit", ":q"}:
                    break
                if not text:
                    continue
                result = await runner.send(text)
                typer.echo(f"artemis> {result.output}")
                for artifact in result.artifacts:
                    typer.echo(f"  [{artifact['kind']}] {artifact['path']}")


@app.command("import")
def import_command(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    currency: str = typer.Option("USD", help="Default currency for the file."),
    dayfirst: bool = typer.Option(False, "--dayfirst", help="Interpret DD/MM/YYYY dates."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse only; do not write."),
) -> None:
    """Import transactions from a CSV/bank statement."""
    runtime = build_runtime()
    text = file.read_text(encoding="utf-8")
    with repositories(runtime) as repos:
        deps = build_deps(runtime, repos)
        if dry_run:
            from artemis.domain.imports import parse_csv

            parsed = parse_csv(text, default_currency=currency, dayfirst=dayfirst)
            typer.echo(f"parsed {len(parsed.rows)} rows, {len(parsed.warnings)} warnings")
            for warning in parsed.warnings:
                typer.echo(f"  ! {warning}")
            return
        try:
            summary = ledger.import_csv(
                deps, text=text, default_currency=currency, dayfirst=dayfirst
            )
        except ValueError as exc:
            typer.echo(f"import failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(
        f"imported {summary.inserted} transactions "
        f"({summary.skipped} duplicates skipped, {summary.total_rows} rows)"
    )
    for warning in summary.warnings:
        typer.echo(f"  ! {warning}")


@app.command()
def report(
    period: str = typer.Option("this-month", help="A month (2026-01) or keyword."),
    chart: bool = typer.Option(False, "--chart", help="Render a PNG chart via apollo-charting."),
    pdf: bool = typer.Option(False, "--pdf", help="Render a PDF via apollo-pdf-creator."),
    out: Path | None = typer.Option(None, help="Copy artifacts into this directory."),
    currency: str | None = typer.Option(None, help="Restrict to one currency."),
) -> None:
    """Print a spending report and optionally render chart/PDF artifacts."""
    runtime = build_runtime()
    with repositories(runtime) as repos:
        report_model = build_spending_report(repos, period=period, currency=currency)
        typer.echo(render_spending_report(report_model))
        if chart or pdf:
            asyncio_run(_render(runtime.settings, report_model, chart, pdf, out))


async def _render(settings, report_model, want_chart: bool, want_pdf: bool, out: Path | None) -> None:
    registry = MCPRegistry(settings)
    async with registry:
        if registry.errors:
            typer.echo(f"mcp warnings: {registry.errors}", err=True)
        await _render_artifacts(registry, report_model, want_chart, want_pdf, out)


@app.command()
def budget(
    period: str = typer.Option("this-month", help="A month (2026-01) or keyword."),
    set_: str | None = typer.Option(None, "--set", help="Category to budget."),
    amount: str | None = typer.Option(None, help="Budget amount (with --set)."),
) -> None:
    """Show budget status, or set a category budget with --set/--amount."""
    runtime = build_runtime()
    from artemis.domain.reports import period_bounds

    start, _ = period_bounds(period)
    period_key = f"{start.year:04d}-{start.month:02d}"
    with repositories(runtime) as repos:
        if set_ and amount:
            currency = "USD"
            from artemis.domain.money import format_minor, parse_amount

            category = repos.categories.get_by_name(set_) or repos.categories.create(set_)
            assert category.id is not None
            budget_model = repos.budgets.upsert(
                category.id, period_key, parse_amount(amount, currency), currency
            )
            typer.echo(
                f"budget set: {category.name} {period_key} "
                f"{format_minor(budget_model.amount_minor, currency)}"
            )
            return
        status = build_budget_status(repos, period=period_key)
    typer.echo(render_budget_status(status))


@app.command()
def portfolio(
    add: str | None = typer.Option(None, "--add", help="Symbol to add/update."),
    quantity: float | None = typer.Option(None, help="Units (with --add)."),
    cost: str | None = typer.Option(None, help="Total cost basis (with --add)."),
    price: str | None = typer.Option(None, "--price", help="Symbol to set a price for."),
    value: str | None = typer.Option(None, help="Price per unit (with --price)."),
) -> None:
    """Show the portfolio, add a holding, or set a price."""
    runtime = build_runtime()
    from decimal import Decimal

    from artemis.domain.money import parse_amount

    with repositories(runtime) as repos:
        if add and quantity is not None and cost:
            repos.holdings.upsert(add, Decimal(str(quantity)), cost_basis_minor=parse_amount(cost))
        if price and value:
            holding = repos.holdings.get_by_symbol(price)
            currency = holding.currency if holding else "USD"
            repos.prices.add(price, parse_amount(value, currency), currency=currency)
        summary = summarize_portfolio(repos)
    typer.echo(render_portfolio(summary))


@app.command()
def backup(out: Path = typer.Argument(..., dir_okay=False)) -> None:
    """Back up the local database file to OUT."""
    settings = get_settings()
    if settings.libsql_url and not settings.libsql_url.startswith("sqlite"):
        typer.echo("backup supports only the local SQLite/libSQL file", err=True)
        raise typer.Exit(code=1)
    source = settings.db_path
    if not source.exists():
        typer.echo(f"no database at {source}", err=True)
        raise typer.Exit(code=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)
    typer.echo(f"backed up {source} -> {out}")


@app.command("export")
def export_data(
    out: Path = typer.Option(..., "--out", dir_okay=False),
    format: str = typer.Option("csv", "--format", help="csv or json"),
) -> None:
    """Export all transactions to CSV or JSON."""
    import csv as _csv
    import json as _json

    runtime = build_runtime()
    with repositories(runtime) as repos:
        categories = {c.id: c.name for c in repos.categories.list()}
        records = [
            {
                "id": row.id,
                "posted_at": row.posted_at.isoformat(),
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "description": row.description,
                "merchant": row.merchant,
                "category": categories.get(row.category_id),
                "source": row.source,
                "external_id": row.external_id,
            }
            for row in repos.transactions.list()
        ]
    out.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        out.write_text(_json.dumps(records, indent=2), encoding="utf-8")
    else:
        fieldnames = list(records[0].keys()) if records else ["id"]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
    typer.echo(f"exported {len(records)} transactions -> {out}")


@app.command()
def bot() -> None:
    """Run the Telegram bot (long-polling)."""
    from artemis.gateways.telegram_bot import run_bot

    _enable_observability()
    run_bot(get_settings())


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="stdio | streamable-http | sse"),
    host: str | None = typer.Option(None, help="Bind host (HTTP transports)."),
    port: int | None = typer.Option(None, help="Bind port (HTTP transports)."),
) -> None:
    """Run Artemis as an MCP server (full agent + read-only tools)."""
    from artemis.mcp.server import serve

    _enable_observability()
    serve(get_settings(), transport=transport, host=host, port=port)


@app.command()
def a2a() -> None:
    """Run Artemis as an A2A server (agent card + JSON-RPC)."""
    from artemis.a2a.server import serve

    _enable_observability()
    serve(get_settings())


@app.command()
def worker() -> None:
    """Run the durable worker (DBOS queues + cron schedules)."""
    import time

    from agentkit import scheduler

    from artemis import durability

    _enable_observability()
    settings = get_settings()
    durability.init(settings)  # register the report queue
    scheduler.init_scheduler(settings)  # register the tick + worker queue
    typer.echo("Artemis worker running (durable queues + schedules). Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:  # pragma: no cover
        typer.echo("worker stopped")


@app.command()
def up(
    a2a: bool = typer.Option(True, "--a2a/--no-a2a", help="Run the A2A server."),
    mcp: bool = typer.Option(True, "--mcp/--no-mcp", help="Run the MCP HTTP server."),
    bot: bool = typer.Option(True, "--bot/--no-bot", help="Run the Telegram bot (if configured)."),
) -> None:
    """Run the whole stack in one process (worker + A2A + MCP + bot + observability).

    The DBOS worker (queues + scheduler tick) starts automatically; with
    `OBSERVABILITY=phoenix` a local Arize Phoenix UI is launched too.
    """
    from agentkit import scheduler
    from agentkit.supervise import Service, run_all

    from artemis import durability

    settings = get_settings()
    run_bot_enabled = bot and bool(settings.telegram_bot_token)
    if not (a2a or mcp or run_bot_enabled):
        typer.echo("nothing to run")
        return

    _enable_observability()
    durability.init(settings)
    scheduler.init_scheduler(settings)

    services: list[Service] = []
    if a2a:
        from artemis.a2a.server import serve as serve_a2a

        services.append(Service("a2a", lambda: serve_a2a(settings)))
    if mcp:
        from artemis.mcp.server import serve as serve_mcp

        services.append(Service("mcp", lambda: serve_mcp(settings, transport="streamable-http")))
    if run_bot_enabled:
        from artemis.gateways.telegram_bot import run_bot

        services.append(Service("bot", lambda: run_bot(settings)))

    typer.echo("artemis up: " + ", ".join(service.name for service in services))
    run_all(services)


@app.command()
def workflows(
    show: str | None = typer.Option(None, "--show", help="Workflow id to inspect."),
    cancel: str | None = typer.Option(None, "--cancel", help="Cancel a workflow id."),
    resume: str | None = typer.Option(None, "--resume", help="Resume a workflow id."),
    status: str | None = typer.Option(None, "--status", help="Filter by status (e.g. ERROR)."),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Inspect and manage durable (DBOS) workflows."""
    from artemis import durability

    db = durability.client(get_settings())
    if cancel:
        db.cancel_workflow(cancel)
        typer.echo(f"cancelled {cancel}")
        return
    if resume:
        db.resume_workflow(resume)
        typer.echo(f"resumed {resume}")
        return
    if show:
        wf = db.retrieve_workflow(show).get_status()
        typer.echo(f"{wf.workflow_id}  {wf.status}  {wf.name}  queue={wf.queue_name}")
        return
    rows = db.list_workflows(status=status, limit=limit, sort_desc=True)
    if not rows:
        typer.echo("no workflows")
        return
    for row in rows:
        typer.echo(f"{row.workflow_id[:14]}  {str(row.status):24}  {row.name}")


@app.command("job-report")
def job_report(
    period: str = typer.Option("this-month", help="A month (2026-01) or keyword."),
    chart: bool = typer.Option(False, "--chart"),
    pdf: bool = typer.Option(False, "--pdf"),
    enqueue: bool = typer.Option(False, "--enqueue", help="Queue and return instead of waiting."),
) -> None:
    """Run a durable spending-report job (survives restarts)."""
    from artemis import durability

    settings = get_settings()
    if enqueue:
        workflow_id = durability.enqueue_report_job(
            period, chart=chart, pdf=pdf, settings=settings
        )
        typer.echo(f"queued report job: {workflow_id}")
        return
    result = durability.run_report_job(period, chart=chart, pdf=pdf)
    typer.echo(result["text"])
    for artifact in result["artifacts"]:
        typer.echo(f"{artifact['kind']}: {artifact['path']}")


@app.command("job-turn")
def job_turn(
    text: str = typer.Argument(..., help="Prompt for the agent."),
    conversation_id: str = typer.Option("cli:durable", help="Conversation id."),
) -> None:
    """Run a durable agent turn (checkpointed; resumable across restarts)."""
    from artemis import durability

    result = durability.run_turn(text, conversation_id=conversation_id, settings=get_settings())
    typer.echo(result["output"])
    for artifact in result["artifacts"]:
        typer.echo(f"  [{artifact['kind']}] {artifact['path']}")


@app.command("schedule-list")
def schedule_list() -> None:
    """List durable scheduled jobs (cron and one-off)."""
    from artemis import durability

    jobs = durability.list_report_schedules()
    if not jobs:
        typer.echo("no scheduled jobs")
        return
    for job in jobs:
        state = "on" if job["enabled"] else "off"
        typer.echo(f"{job['name']} [{job['kind']}/{state}] {job['schedule']} -> {job['task']} {job['args']}")


@app.command("schedule-add-report")
def schedule_add_report(
    name: str = typer.Option(..., "--name", help="Schedule name."),
    cron: str | None = typer.Option(None, "--cron", help="Cron expression, e.g. '0 8 * * 1'."),
    at: str | None = typer.Option(None, "--at", help="One-off ISO datetime, e.g. 2026-11-01T09:00."),
    period: str = typer.Option("last-month", help="Report period."),
    chart: bool = typer.Option(False, "--chart"),
    pdf: bool = typer.Option(False, "--pdf"),
) -> None:
    """Schedule a recurring (--cron) or one-off (--at) spending report."""
    from artemis import durability

    try:
        durability.schedule_report(
            name=name, period=period, chart=chart, pdf=pdf, cron=cron, at=at,
            settings=get_settings(),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    when = cron or at
    typer.echo(f"schedule '{name}' registered ({when}); run 'artemis worker' to execute it")


@app.command("schedule-remove")
def schedule_remove(name: str = typer.Argument(...)) -> None:
    """Remove a scheduled job."""
    from artemis import durability

    removed = durability.remove_report_schedule(name)
    typer.echo("removed" if removed else "not found")


def _enable_observability() -> None:
    """Enable tracing for long-running commands (not one-shot CLI calls)."""
    from artemis.observability import setup_observability

    setup_observability(get_settings())


def main() -> None:
    from artemis.observability import setup_logging

    setup_logging(get_settings())
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
