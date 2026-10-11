"""In-process smoke test for the read-only Artemis MCP server.

Run with `uv run python tests/mcp_smoke.py`. No network, no subprocesses.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import date
from pathlib import Path

from fastmcp import Client
from sqlmodel import Session

from artemis.config import Settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.db.repos import Repositories
from artemis.mcp.server import build_server
from artemis.services.runtime import Runtime


async def main() -> None:
    home = Path(tempfile.mkdtemp())
    engine = create_db_engine(f"sqlite+libsql:///{home / 'artemis.db'}")
    bootstrap(engine, "owner", "Owner")
    runtime = Runtime(
        settings=Settings(owner_id="owner", artemis_home=home),
        engine=engine,
        session_factory=make_session_factory(engine),
    )
    with Session(engine) as session:
        repos = Repositories(session, "owner")
        repos.transactions.add(posted_at=date(2026, 1, 5), amount_minor=-4250, merchant="Whole Foods")
        session.commit()

    server = build_server(runtime.settings, runtime)
    async with Client(server) as client:
        tools = sorted(tool.name for tool in await client.list_tools())
        print("tools:", tools)
        result = await client.call_tool("query_spending", {"period": "2026-01"})
        data = result.structured_content
        payload = data.get("result", data) if isinstance(data, dict) else data
        print("total_spend_minor:", payload["total_spend_minor"])
        assert payload["total_spend_minor"] == 4250
    print("MCP SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
