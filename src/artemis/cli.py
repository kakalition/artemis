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


@app.command()
def chat(
    conv: str = typer.Option("cli:default", help="Conversation id."),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Do not connect to the apollo MCP servers."),
) -> None:
    """Interactive chat with the finance agent."""
    asyncio_run(_chat(conv, with_mcp=not no_mcp))


async def _chat(conv: str, with_mcp: bool) -> None:
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
        summary = ledger.import_csv(
            deps, text=text, default_currency=currency, dayfirst=dayfirst
        )
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
def bot() -> None:
    """Run the Telegram bot (long-polling)."""
    from artemis.gateways.telegram_bot import run_bot

    run_bot(get_settings())


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="stdio | streamable-http | sse"),
    host: str | None = typer.Option(None, help="Bind host (HTTP transports)."),
    port: int | None = typer.Option(None, help="Bind port (HTTP transports)."),
) -> None:
    """Run Artemis as an MCP server (full agent + read-only tools)."""
    from artemis.mcp.server import serve

    serve(get_settings(), transport=transport, host=host, port=port)


@app.command()
def a2a() -> None:
    """Run Artemis as an A2A server (agent card + JSON-RPC)."""
    from artemis.a2a.server import serve

    serve(get_settings())


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
