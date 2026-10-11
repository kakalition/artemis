# Artemis

**A personal finance agent** — track spending, budgets, goals and a portfolio,
ask questions about your money, and generate chart/PDF reports — through a CLI
and a Telegram bot, with an MCP server and an A2A endpoint.

Built on [**agentkit**](https://github.com/kakalition/agentkit) (PydanticAI v2 +
durable execution + MCP/A2A), **libSQL**, and a set of local MCP servers for
charts and PDFs. Artemis is the finance domain; agentkit is the plumbing.

[![CI](https://github.com/kakalition/artemis/actions/workflows/ci.yml/badge.svg)](https://github.com/kakalition/artemis/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-119-brightgreen)

> Educational guidance only — not regulated financial advice. Artemis never
> moves money.

---

## Why Artemis

- **Ask your money anything.** "How much did I spend on groceries last month?",
  "am I on budget?", "what's my portfolio worth?" — answered from your real data.
- **Numbers you can trust.** Every amount is integer minor units + an ISO
  currency; no `float` anywhere, no silent FX conversions.
- **Six specialists, one agent.** Transactions, budgets, goals, portfolio,
  insights, and reports, behind a routing orchestrator.
- **Reports you can keep.** One command turns a month into a Markdown summary, a
  PNG chart, or a PDF — on demand or on a schedule.
- **Durable and safe.** Bulk/destructive actions require approval; every write is
  audited; background jobs survive restarts.
- **An operator console.** `artemis up` serves a web UI for chat, spending,
  schedules, workflows, usage, audit, and your persona.

## Table of contents

- [Why Artemis](#why-artemis)
- [Features](#features)
- [Install](#install)
- [Configure](#configure)
- [CLI](#cli)
- [Web UI](#web-ui)
- [CSV import](#csv-import)
- [Telegram](#telegram)
- [MCP](#mcp)
- [A2A](#a2a)
- [Durability & scheduling](#durability--scheduling)
- [Persona (`SOUL.md`)](#persona-soulmd)
- [Observability](#observability)
- [Data model & money rules](#data-model--money-rules)
- [Security](#security)
- [Deployment](#deployment)
- [Development](#development)
- [License](#license)

## Features

- **Six specialists** behind one orchestrator: transactions, budgets, goals,
  portfolio, insights, and reports (charts/PDF).
- **Money discipline**: every amount is integer minor units + an ISO-4217
  currency. No `float` on any monetary path; reports group by currency and never
  convert.
- **Durable history** in libSQL, keyed by `cli:default` / `tg:<chat_id>` /
  `a2a:default`.
- **Human-in-the-loop**: bulk (`import_transactions`) and destructive
  (`delete_transaction`) tools pause for approval — a CLI prompt or Telegram
  inline buttons — via PydanticAI deferred tools.
- **Durable & resilient**: DBOS durable turns/jobs, durable **cron + one-off**
  scheduling, model timeouts/retries, optional per-run usage caps.
- **Persona `SOUL.md`**: identity/behaviour is Markdown (project root or
  `$ARTEMIS_HOME`), composed with routing instructions.
- **Operational**: structured JSON logs with correlation ids and redaction,
  per-turn **token accounting**, a hash-chained **audit log**, readiness
  (`/readyz`) and graceful shutdown.
- **MCP both ways**: consumes `apollo-charting` + `apollo-pdf-creator`, and
  serves a **full-agent** MCP server plus typed read-only tools.
- **A2A both ways**: task-based server with a durable task store; the
  orchestrator can call configured remote agents.

## Install

```bash
git clone https://github.com/kakalition/artemis && cd artemis
./install.sh                       # uv sync (incl. the local Phoenix observability UI)
cp .env.example .env               # then edit
```

Requires **Python 3.11–3.12** and [uv](https://docs.astral.sh/uv/). Optional free
market data: `uv sync --extra prices`.

### Quickstart

```bash
export OPENAI_API_KEY=sk-...          # or put it in .env
uv run artemis import statement.csv   # import a bank statement
uv run artemis report --period 2025-01 --chart
uv run artemis up                     # worker + A2A + MCP + bot + web UI (:8787)
```

## Configure

Environment variables (see `.env.example`); `.env` is loaded automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | – | Model credential |
| `OPENAI_BASE_URL` | – | Any OpenAI-compatible gateway |
| `MODEL_NAME` | `openai:gpt-4o-mini` | Model id |
| `MODEL_TIMEOUT` / `MODEL_RETRIES` | `60` / `2` | Transport resilience |
| `USAGE_REQUEST_LIMIT` / `USAGE_TOTAL_TOKENS_LIMIT` | (unlimited) | Per-run caps |
| `OWNER_ID` / `OWNER_NAME` | `owner` / `Owner` | The owner |
| `LIBSQL_URL` / `LIBSQL_AUTH_TOKEN` | local file | `sqlite+libsql://…` or Turso |
| `AGENTKIT_HOME` | `~/.agentkit` | Workspace root (`~/.agentkit/artemis`) |
| `ARTEMIS_HOME` / `AGENT_HOME` | `~/.agentkit/artemis` | Explicit home override |
| `SOUL_FILE` | `./SOUL.md` or `$AGENT_HOME/SOUL.md` | Persona |
| `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` | `true` / `127.0.0.1` / `8787` | Operator web UI |
| `TELEGRAM_BOT_TOKEN` | – | Enables `artemis bot` |
| `TELEGRAM_ALLOWED_CHAT_IDS` | (all) | Chat allowlist |
| `PRICE_SOURCE` | `manual` | `manual` or `yfinance` |
| `MAX_IMPORT_BYTES` | `5000000` | Reject larger CSV imports |
| `CHARTING_DIR` / `PDF_DIR` | apollo checkouts | MCP servers |
| `CHARTING_MCP_URL` / `PDF_MCP_URL` | – | HTTP transport instead of stdio |
| `A2A_PUBLIC_URL` / `A2A_HOST` / `A2A_PORT` | `http://127.0.0.1:9000` | A2A |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | MCP HTTP |
| `PEERS_FILE` | – | `peers.json` of remote A2A agents |
| `OBSERVABILITY` | `phoenix` | `phoenix` (local UI) \| `console` \| `otlp` \| `off` |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | Logging |

## CLI

```bash
artemis up                                     # everything: worker + A2A + MCP + bot + web UI
artemis chat                                   # interactive agent
artemis import statement.csv [--dayfirst]      # import CSV/bank statement
artemis report --period 2026-01 [--chart --pdf] [--out DIR]
artemis budget --period 2026-01                # status
artemis budget --set Groceries --amount 500    # set
artemis portfolio [--add SYMBOL --quantity 2 --cost 300] [--price SYMBOL --value 160]
artemis bot                                    # Telegram long-polling
artemis mcp [--transport stdio|streamable-http|sse]
artemis a2a                                    # A2A server
artemis worker                                 # durable worker (queues + schedules)
artemis job-report --period last-month [--chart --pdf] [--enqueue]
artemis job-turn "how much did I spend this month?"
artemis schedule-add-report --name weekly --cron "0 8 * * 1" --period last-month
artemis schedule-add-report --name reminder --at 2026-11-01T09:00 --period last-month
artemis schedule-list / schedule-remove
artemis workflows [--status ERROR] [--show ID] [--cancel ID] [--resume ID]
artemis backup ~/artemis-backup.db ; artemis export --out tx.json --format json
artemis db upgrade ; artemis soul [--init]
```

## Web UI

`artemis up` also serves an operator web UI at `http://127.0.0.1:8787` (loopback,
no auth) for **this agent only**: inspect conversations/chat, usage, audit, A2A
tasks and durable workflows; manage schedules, cancel/resume workflows, edit the
SOUL persona, view config (secrets masked) and artifacts. Chat runs through the
same `ChatRunner`/orchestrator as the CLI, so history is shared. Data now lives
under `~/.agentkit/artemis` (see `agentkit workspace migrate artemis` if you are
upgrading from `~/.local/share/artemis`).

## CSV import

Canonical columns (case-insensitive; aliases in parentheses):

| Column | Required | Notes |
| --- | --- | --- |
| `date` | yes | `posted_at`, `transaction_date`; ISO or `MM/DD/YYYY` (`--dayfirst` for `DD/MM/YYYY`) |
| `amount` | yes* | `value`; `-42.50`, `$1,234.56`, `(42.00)` |
| `description` | yes | `memo`, `narrative`, `details` |
| `currency` | no | `ccy`; defaults to `--currency` |
| `merchant` | no | `payee`, `counterparty` |
| `external_id` | no | `id`, `reference`; used to dedupe |
| `category` | no | `category_name` |
| `debit` / `credit` | no | Used when `amount` is absent |

Bad rows never abort an import; they are reported as warnings. Imports larger
than `MAX_IMPORT_BYTES` are rejected.

## Telegram

`artemis bot` runs long-polling. Each chat is a conversation (`tg:<chat_id>`).
Replies render Markdown → Telegram entities (telegramify-markdown) with a
plain-text fallback. Approvals arrive as inline ✅/❌ buttons. Charts/PDFs are
delivered as photos/documents. Restrict access with `TELEGRAM_ALLOWED_CHAT_IDS`.

## MCP

**Client.** Artemis consumes the apollo servers with prefixed toolsets so the
shared `validate_spec` tool does not collide (`chart_*` / `pdf_*`). Toolset
lifecycle is process-owned; each server is launched with
`uv run --directory <server> <script>`, logs go to `$ARTEMIS_HOME/logs/`, and
the client uses the newest FastMCP protocol negotiation.

**Server.** `artemis mcp` exposes the **full agent** plus typed read-only tools:

| Tool | Does |
| --- | --- |
| `ask_artemis(prompt, conversation_id="mcp:default")` | Runs the full agent (reads + normal writes) |
| `query_spending(period, currency, top_n)` | `SpendingReport` |
| `get_budget_status(period, currency)` | `BudgetStatus` |
| `get_portfolio_summary(currency)` | `PortfolioSummary` |
| `list_goals()` | `list[GoalRecord]` |

Bulk/destructive tools stay approval-gated and are **denied** over MCP unless
`MCP_AUTO_APPROVE=true` (dangerous, opt-in). HTTP transports bind loopback by
default and warn if exposed.

## A2A

Both directions use the official **`a2a-sdk`**. `artemis a2a` serves the agent
card at `/.well-known/agent-card.json` and JSON-RPC at `/`. The executor uses the
SDK's **task-based** flow (`submitted → working → completed`/`failed`) with the
reply as an artifact; tasks persist in libSQL (`a2a_tasks`), so they survive
restarts and are queryable via `tasks/get`/`ListTasks`. The outbound client
resolves the peer's card and calls `message/send`.

## Durability & scheduling

Long/background work runs on **DBOS Transact** on a local SQLite system DB — no
server. Workflows are checkpointed and steps retry with backoff.

| Kind | API | CLI |
| --- | --- | --- |
| Agent turn | `durability.run_turn` | `artemis job-turn` |
| Report job | `durability.run_report_job` | `artemis job-report` |
| Background queue | `enqueue_*` | `artemis worker` |
| Cron / one-off schedule | `durability.schedule_report` → `agentkit.scheduler` | `artemis schedule-add-report` |
| Workflow management | `durability.list_workflows`/`cancel`/`resume` | `artemis workflows` |

```bash
artemis schedule-add-report --name weekly --cron "0 8 * * 1" --period last-month --pdf
artemis schedule-add-report --name reminder --at 2026-11-01T09:00 --period last-month
artemis worker        # executes the queue + the minute scheduler tick
```

## Persona (`SOUL.md`)

The agent's identity/behaviour lives in Markdown, composed with the routing
instructions — edit the persona without touching code.

```bash
artemis soul          # show the active persona
artemis soul --init   # scaffold a SOUL.md
```

## Observability

**On by default** with a local **Arize Phoenix** UI (self-hosted, no account);
`console` and `otlp` (Jaeger/Tempo/Langfuse/collector) are available, and the
mode falls back to console when Phoenix isn't installed.

```bash
artemis up                                 # launches Phoenix (localhost:6006)
OBSERVABILITY=otlp OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces artemis up
```

## Data model & money rules

`owners, accounts, categories, merchant_rules, transactions, budgets, goals,
goal_contributions, holdings, price_snapshots, conversations, messages,
a2a_tasks, scheduled_jobs, usage_records, audit_log`. Schema is versioned with
**Alembic** (`artemis db upgrade`).

Transactions store `amount_minor` (signed int: negative = spend) + `currency`.
Parsing is `str → Decimal → int`; formatting is `int → Decimal → str`
(Babel/CLDR). Per-transaction currency; no FX conversion.

## Security

- Loopback-only MCP/A2A binds by default (with an exposure warning).
- Bulk/destructive tools require approval; no writes exposed over MCP by default.
- Imported CSV, MCP resource text and remote replies are passed as **data**, not
  instructions (prompt-injection scanning + untrusted wrapping available).
- Structured logs **redact** secrets and amounts; all writes are **audited**.

## Deployment

`Dockerfile` + `docker-compose.yml` (state in `./data`), plus
`deploy/artemis-bot.service` (systemd) and `deploy/com.artemis.bot.plist`
(launchd). See `deploy/README.md`. The A2A server exposes `GET /healthz` and
`GET /readyz` for probes.

## Development

```bash
uv run pytest            # 119 tests (unit + CLI)
uv run ruff check src tests
uv run mypy src/artemis
bash tests/smoke.sh      # CLI end-to-end in a temp HOME
uv run python tests/soak.py 200   # durable-turn soak (no network/cost)
```

Layout: `src/artemis/{config,cli,render,guardrails,soul,observability}.py`,
`domain/` (money, categorizer, imports, reports), `db/`, `agents/`
(orchestrator + six specialists), `services/`, `prices/`, `mcp/`, `a2a/`,
`gateways/`.

## License

MIT.
