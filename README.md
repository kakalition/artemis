# Artemis

A single-user (multi-user-ready) **personal finance agent** built on
[PydanticAI v2](https://pydantic.dev/docs/ai/), exposed through a **Typer CLI**
and an **aiogram Telegram bot**, backed by **libSQL/Turso**, and interoperating
over **MCP** and **A2A**.

Artemis tracks expenses/income, categorizes them (rules first, LLM fallback),
imports CSV/bank statements, tracks budgets, savings goals and an investment
portfolio, answers spending questions, and renders spending **charts (PNG)** and
**PDF** reports through the two local apollo MCP servers.

> Educational guidance only — not regulated financial advice. Artemis never
> moves money.

Built on established libraries rather than hand-rolled equivalents: **PydanticAI
v2** (agents), **FastMCP** (MCP client + server), **a2a-sdk** (A2A client +
server), **Babel** (currency precision/formatting), **python-dateutil** (dates),
**telegramify-markdown** (Telegram rendering), **aiogram**, **Typer**,
**pydantic-settings**, **SQLModel / SQLAlchemy** over **libSQL**, and **httpx**.

## Features

- **Six specialists** behind one orchestrator: transactions, budgets, goals,
  portfolio, insights, and reports (charts/PDF).
- **Money discipline**: every amount is integer minor units + an ISO-4217
  currency. No `float` on any monetary path; reports group by currency and never
  convert.
- **Durable history**: conversations persist in libSQL via PydanticAI's message
  adapter, keyed by `cli:default` / `tg:<chat_id>` / `a2a:default`.
- **Human-in-the-loop**: bulk (`import_transactions`) and destructive
  (`delete_transaction`) tools pause for approval — a CLI prompt or Telegram
  inline buttons — via PydanticAI deferred tools.
- **Durable & resilient**: DBOS durable workflows/queues/schedules on a local
  SQLite system DB **and** A2A tasks persisted in libSQL (survive restarts);
  model timeouts, SDK retries, optional per-run usage caps, and optional
  Logfire/OTel instrumentation.
- **MCP both ways**: consumes `apollo-charting` + `apollo-pdf-creator`, and
  serves a **full-agent** MCP server plus typed read-only tools.
- **A2A both ways**: publishes an agent card + JSON-RPC server; the orchestrator
  can call configured remote agents.

## Install

```bash
git clone <repo> artemis && cd artemis
./install.sh                      # uv sync --extra dev
cp .env.example .env              # then edit
```

Requires **Python 3.11–3.12** and [uv](https://docs.astral.sh/uv/). Optional
free market data: `uv sync --extra prices` (installs `yfinance`).

## Configure

All settings are environment variables (see `.env.example`); `.env` is loaded
automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | – | Model credential. |
| `OPENAI_BASE_URL` | – | Point at any OpenAI-compatible gateway. |
| `MODEL_NAME` | `openai:gpt-4o-mini` | PydanticAI model id. |
| `MODEL_TIMEOUT` / `MODEL_RETRIES` | `60` / `2` | Per-request timeout and SDK retries. |
| `USAGE_REQUEST_LIMIT` / `USAGE_TOTAL_TOKENS_LIMIT` | (unlimited) | Optional per-run caps. |
| `OBSERVABILITY` | `off` | `off` \| `console` (local) \| `otlp` (local backend) \| `logfire` (cloud free tier). |
| `OTLP_ENDPOINT` | – | OTLP endpoint for `observability=otlp`. |
| `LOGFIRE_TOKEN` | – | Token for `observability=logfire` (also enables cloud if set). |
| `MAX_IMPORT_BYTES` | `5000000` | Reject larger CSV imports. |
| `OWNER_ID` / `OWNER_NAME` | `owner` / `Owner` | The single owner. |
| `LIBSQL_URL` | local file under `ARTEMIS_HOME` | `sqlite+libsql:///…` or Turso. |
| `LIBSQL_AUTH_TOKEN` | – | Turso auth token. |
| `ARTEMIS_HOME` | `~/.local/share/artemis` | DB + artifacts directory. |
| `TELEGRAM_BOT_TOKEN` | – | Enables `artemis bot`. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | (all) | Comma/space-separated chat allowlist. |
| `PRICE_SOURCE` | `manual` | `manual` or `yfinance`. |
| `CHARTING_DIR` / `PDF_DIR` | apollo checkouts | Where the MCP servers live. |
| `CHARTING_MCP_URL` / `PDF_MCP_URL` | – | Use HTTP transport instead of stdio. |
| `A2A_PUBLIC_URL` | `http://127.0.0.1:9000` | Advertised card URL. |
| `A2A_HOST` / `A2A_PORT` | `127.0.0.1` / `9000` | A2A bind address. |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | MCP HTTP bind address. |
| `PEERS_FILE` | – | `peers.json` of remote A2A agents. |

## CLI

```bash
artemis chat                                   # interactive agent (CLI conversation)
artemis import statement.csv [--dayfirst]      # import CSV/bank statement
artemis report --period 2026-01 [--chart --pdf] [--out DIR]
artemis budget --period 2026-01                # status
artemis budget --set Groceries --amount 500    # set
artemis portfolio                              # summary
artemis portfolio --add AAPL --quantity 2 --cost 300
artemis portfolio --price AAPL --value 160
artemis bot                                    # Telegram long-polling
artemis mcp [--transport stdio|streamable-http|sse]
artemis a2a                                    # A2A server
artemis worker                                 # durable worker (queues + cron schedules)
artemis job-report --period last-month [--chart --pdf] [--enqueue]
artemis job-turn "how much did I spend this month?"
artemis schedule-add-report --name weekly --cron "0 8 * * 1" --period last-month
artemis schedule-list
artemis backup ~/artemis-backup.db             # copy the local database
artemis export --out transactions.json --format json
artemis db upgrade                             # apply Alembic migrations
artemis db revision -m "add something"         # autogenerate a migration
```

`report --chart/--pdf` renders artifacts through the MCP servers **without** an
LLM; the artifact's absolute path is printed and optionally copied with `--out`.

### CSV import

Canonical columns (case-insensitive; aliases in parentheses):

| Column | Required | Notes |
| --- | --- | --- |
| `date` | yes | `posted_at`, `transaction_date`; ISO or `MM/DD/YYYY` (`--dayfirst` for `DD/MM/YYYY`). |
| `amount` | yes* | `value`; `-42.50`, `$1,234.56`, `(42.00)`. |
| `description` | yes | `memo`, `narrative`, `details`. |
| `currency` | no | `ccy`; defaults to `--currency`. |
| `merchant` | no | `payee`, `counterparty`. |
| `external_id` | no | `id`, `reference`; used to dedupe. Synthesized when absent. |
| `category` | no | `category_name`. |
| `debit` / `credit` | no | Used when `amount` is absent (debit = outflow). |

Bad rows never abort an import; they are reported as warnings.

## Telegram

`artemis bot` runs long-polling. Each chat is a conversation (`tg:<chat_id>`).
Replies are rendered from Markdown to Telegram entities with
[`telegramify-markdown`](https://pypi.org/project/telegramify-markdown/) (which
converts, escapes and splits into ≤4096-char messages), with a plain-text
fallback if Telegram rejects an entity. Approvals arrive as inline ✅/❌ buttons.
Charts/PDFs are delivered as photos/documents. Restrict access with
`TELEGRAM_ALLOWED_CHAT_IDS`.

## MCP

**Client.** Artemis consumes the apollo servers with prefixed toolsets so the
shared `validate_spec` tool does not collide:

| Prefix | Server | Tools |
| --- | --- | --- |
| `chart_` | apollo-charting | `render_chart`, `validate_spec`, `chart_component` |
| `pdf_` | apollo-pdf-creator | `create_pdf`, `validate_spec`, `from_markdown` |

Toolset lifecycle is owned by the process (entered once, closed on shutdown);
`artemis bot`/`a2a` prefer HTTP transport (`CHARTING_MCP_URL`/`PDF_MCP_URL`) so a
restart does not orphan stdio subprocesses. Each server is launched with
`uv run --directory <server> <console-script>` and its logs go to
`$ARTEMIS_HOME/logs/` rather than the console. The client uses the newest
FastMCP protocol negotiation, which gracefully falls back for the
handshake-era apollo servers.

**Server.** `artemis mcp` exposes the **full agent** plus typed read-only tools:

| Tool | Does |
| --- | --- |
| `ask_artemis(prompt, conversation_id="mcp:default")` | Runs the full agent — reads and normal writes (record transactions, budgets, goals, portfolio, insights, reports). |
| `query_spending(period, currency, top_n)` | `SpendingReport` |
| `get_budget_status(period, currency)` | `BudgetStatus` |
| `get_portfolio_summary(currency)` | `PortfolioSummary` |
| `list_goals()` | `list[GoalRecord]` |

Plus a resource `artemis://artifact/{name}` for generated reports. Bulk and
destructive tools (`import_transactions`, `delete_transaction`) stay
approval-gated; because there is no interactive approver over MCP they are
**denied** unless you set `MCP_AUTO_APPROVE=true` (dangerous, opt-in). HTTP
transports bind loopback by default and warn if exposed.

## A2A

Both directions use the official **`a2a-sdk`**. `artemis a2a` serves the agent
card at `/.well-known/agent-card.json` and JSON-RPC at `/`. The executor uses the
SDK's **task-based** flow: it enqueues a `Task`, then drives it `submitted →
working → completed` (or `failed`), carrying the reply as an artifact. Tasks are
persisted in libSQL through `LibSQLTaskStore` (the `a2a_tasks` table), so task
state, history and artifacts survive restarts and are queryable via `tasks/get`
and `ListTasks`. The outbound client resolves the peer's card and calls
`message/send` through the SDK.

## Durability

Long/background work runs on **DBOS Transact** — lightweight durable execution
backed by a local SQLite *system database* (`$ARTEMIS_HOME/dbos.sqlite`), with
**no separate server** (unlike Temporal). Workflows are checkpointed: after a
crash or restart, completed steps are not repeated and the run resumes.

| Kind | API | CLI |
| --- | --- | --- |
| Agent turn | `durability.run_turn` / `agent_turn` | `artemis job-turn` |
| Report job | `durability.run_report_job` / `report_job` | `artemis job-report` |
| Background queue | `enqueue_turn` / `enqueue_report_job` (`artemis` queue) | `artemis worker` |
| Cron schedule | `apply_report_schedule` | `artemis schedule-add-report` |

```bash
artemis schedule-add-report --name weekly --cron "0 8 * * 1" --period last-month --pdf
artemis worker      # executes queued jobs and the schedule; survives restarts
```

Steps retry with backoff (`_step_run_agent` uses `retries_allowed`, 3 attempts).

## Deployment

Local-first. `Dockerfile` + `docker-compose.yml` (state in `./data`), plus
`deploy/artemis-bot.service` (systemd) and `deploy/com.artemis.bot.plist`
(launchd). See `deploy/README.md`. The A2A server exposes `GET /healthz`
(database check) for probes.

Outbound, the orchestrator can call peers from `PEERS_FILE`:

```json
{ "peers": { "research": { "url": "http://127.0.0.1:9100", "token": "" } } }
```

## Data model & money rules

`owners, accounts, categories, merchant_rules, transactions, budgets, goals,
goal_contributions, holdings, price_snapshots, conversations, messages,
a2a_tasks`. Schema is versioned with **Alembic** (`alembic/` + `artemis db
upgrade`); `bootstrap()` uses `create_all` for tests and first run. Transactions store `amount_minor` (signed int: negative = spend)
plus `currency`. Parsing is `str → Decimal → int`; formatting is
`int → Decimal → str`. Per-transaction currency; reports group by currency with
no FX conversion.

## Security

- Loopback-only MCP/A2A binds by default (with an exposure warning).
- Read-only MCP server; no writes exposed.
- Imported CSV, MCP resource text and remote replies are passed as **data**, not
  instructions.
- No secrets or raw amounts are logged.

## Development

```bash
uv run pytest                      # unit tests (in-process, no network)
uv run pytest -m integration       # real apollo stdio round-trip (self-skips)
uv run ruff check src tests
bash tests/smoke.sh                # CLI end-to-end in a temp HOME
uv run python tests/mcp_smoke.py   # in-process MCP server round-trip
uv run python tests/soak.py 200    # durable-turn soak (no network/cost)
```

Layout: `src/artemis/{config,cli,render,guardrails}.py`,
`domain/` (money, categorizer, imports, reports), `db/` (engine, models,
migrations, repos), `agents/` (orchestrator + six specialists), `services/`
(runtime, ledger, session), `prices/`, `mcp/` (client registry + server),
`a2a/` (client + server), `gateways/telegram_bot.py`.

## License

MIT.
