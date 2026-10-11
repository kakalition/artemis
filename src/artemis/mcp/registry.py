"""MCP client registry for the apollo charting and PDF servers.

Both external servers expose a ``validate_spec`` tool, so every toolset is
prefix-separated (``chart_*`` / ``pdf_*``). The registry owns both toolsets for
the lifetime of the process: enter once at start, close on shutdown — a long
running bot must not auto-open a stdio subprocess per message.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from fastmcp import Client as FastMCPClient
from pydantic_ai.mcp import MCPToolset, StdioTransport

from artemis.config import Settings


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(_text(v) for v in value)
    data = getattr(value, "data", None)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(value)


class MCPRegistry:
    """Owns the chart + PDF ``MCPToolset``s and their schemas."""

    def __init__(
        self,
        settings: Settings,
        *,
        chart_client: Any | None = None,
        pdf_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._chart_client_override = chart_client
        self._pdf_client_override = pdf_client
        self._stack: AsyncExitStack | None = None
        self._chart_raw: MCPToolset | None = None
        self._pdf_raw: MCPToolset | None = None
        self.chart: Any | None = None
        self.pdf: Any | None = None
        self.chart_schema: str | None = None
        self.pdf_schema: str | None = None
        self.errors: dict[str, str] = {}

    # -- construction ----------------------------------------------------
    def _stdio(self, dir_path: Any, script: str, log_var: str, log_name: str) -> StdioTransport:
        import os

        # Run each MCP server in its own uv project (`uv run --directory`), with
        # its logs routed to a file instead of Artemis's console. VIRTUAL_ENV is
        # dropped so the nested `uv run` does not warn about the outer venv.
        env = {**os.environ, log_var: os.environ.get(log_var, "ERROR")}
        env.pop("VIRTUAL_ENV", None)
        log_dir = self.settings.artemis_home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return StdioTransport(
            command="uv",
            args=["run", "--directory", str(dir_path), script],
            env=env,
            log_file=log_dir / log_name,
        )

    def _chart_client(self) -> Any:
        if self._chart_client_override is not None:
            return self._chart_client_override
        if self.settings.charting_mcp_url:
            return self.settings.charting_mcp_url
        return self._stdio(
            self.settings.charting_path,
            "apollo-charting",
            "APOLLO_CHARTING_LOG_LEVEL",
            "apollo-charting.log",
        )

    def _pdf_client(self) -> Any:
        if self._pdf_client_override is not None:
            return self._pdf_client_override
        if self.settings.pdf_mcp_url:
            return self.settings.pdf_mcp_url
        return self._stdio(
            self.settings.pdf_path,
            "apollo-pdf-creator",
            "APOLLO_PDF_LOG_LEVEL",
            "apollo-pdf-creator.log",
        )

    @staticmethod
    def _toolset(transport: Any) -> MCPToolset:
        # Default (newest) FastMCP client negotiation: it prefers the modern
        # protocol and falls back for handshake-era servers.
        client = FastMCPClient(transport)
        return MCPToolset(client, include_instructions=True)

    def build(self) -> None:
        self._chart_raw = self._toolset(self._chart_client())
        self._pdf_raw = self._toolset(self._pdf_client())
        self.chart = self._chart_raw.prefixed("chart")
        self.pdf = self._pdf_raw.prefixed("pdf")

    # -- lifecycle -------------------------------------------------------
    async def __aenter__(self) -> MCPRegistry:
        self.build()
        self._stack = AsyncExitStack()
        await self._enter_one("chart", self.chart, "charting://schema")
        await self._enter_one("pdf", self.pdf, "pdfcreator://schema")
        return self

    async def _enter_one(self, name: str, toolset: Any, schema_uri: str) -> None:
        assert self._stack is not None
        try:
            await self._stack.enter_async_context(toolset)
        except Exception as exc:  # pragma: no cover - depends on external servers
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            if name == "chart":
                self.chart = None
            else:
                self.pdf = None
            return
        try:
            resource = await self.read_resource(name, schema_uri)
            if name == "chart":
                self.chart_schema = resource
            else:
                self.pdf_schema = resource
        except Exception as exc:  # pragma: no cover
            self.errors[f"{name}:schema"] = f"{type(exc).__name__}: {exc}"

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    # -- accessors -------------------------------------------------------
    def toolsets(self) -> list[Any]:
        return [ts for ts in (self.chart, self.pdf) if ts is not None]

    @property
    def available(self) -> bool:
        return bool(self.toolsets())

    async def read_resource(self, which: str, uri: str) -> str:
        raw = {"chart": self._chart_raw, "pdf": self._pdf_raw}.get(which)
        if raw is None:
            raise RuntimeError(f"{which} toolset is not configured")
        return _text(await raw.read_resource(uri))

    async def tool_names(self) -> list[str]:
        """Raw (unprefixed) tool names exposed by each reachable server."""
        names: list[str] = []
        for name, raw in (("chart", self._chart_raw), ("pdf", self._pdf_raw)):
            if raw is None:
                continue
            try:
                tools = await raw.client.list_tools()
                names.extend(f"{name}:{tool.name}" for tool in tools)
            except Exception as exc:  # pragma: no cover
                self.errors[f"{name}:tools"] = f"{type(exc).__name__}: {exc}"
        return names

    async def call_tool(self, which: str, tool: str, arguments: dict[str, Any]) -> Any:
        """Call a raw tool on one of the servers (used by the CLI renderer)."""
        raw = {"chart": self._chart_raw, "pdf": self._pdf_raw}.get(which)
        if raw is None:
            raise RuntimeError(f"{which} MCP server is not available")
        return await raw.client.call_tool(tool, arguments)

    @staticmethod
    def prefixed_tool_name(server: str, tool: str) -> str:
        return f"{server}_{tool}"


def extract_metadata_blocks(result: Any) -> list[dict[str, Any]]:
    """Pull JSON metadata blocks out of an MCP tool result (``out`` path etc.)."""
    import json

    blocks: list[dict[str, Any]] = []
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        blocks.append(structured)
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks
