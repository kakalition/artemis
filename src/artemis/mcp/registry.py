"""Apollo MCP client registry (charting + PDF), built on agentkit's registry."""

from __future__ import annotations

from typing import Any

from agentkit.mcp.registry import MCPRegistry as _BaseRegistry
from agentkit.mcp.registry import MCPServerSpec, extract_metadata_blocks, first_out

from artemis.config import Settings

__all__ = ["MCPRegistry", "MCPServerSpec", "extract_metadata_blocks", "first_out"]


class MCPRegistry(_BaseRegistry):
    """Owns the apollo-charting and apollo-pdf-creator toolsets."""

    def __init__(
        self,
        settings: Settings,
        *,
        chart_client: Any | None = None,
        pdf_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.chart_schema: str | None = None
        self.pdf_schema: str | None = None
        specs = [self._chart_spec(settings), self._pdf_spec(settings)]
        if chart_client is not None:
            specs[0].transport = chart_client
        if pdf_client is not None:
            specs[1].transport = pdf_client
        super().__init__(specs, log_dir=settings.logs_dir)

    @staticmethod
    def _chart_spec(settings: Settings) -> MCPServerSpec:
        if settings.charting_mcp_url:
            return MCPServerSpec(name="chart", url=settings.charting_mcp_url)
        return MCPServerSpec(
            name="chart",
            command="uv",
            args=["run", "--directory", str(settings.charting_path), "apollo-charting"],
            log_var="APOLLO_CHARTING_LOG_LEVEL",
            log_file="apollo-charting.log",
        )

    @staticmethod
    def _pdf_spec(settings: Settings) -> MCPServerSpec:
        if settings.pdf_mcp_url:
            return MCPServerSpec(name="pdf", url=settings.pdf_mcp_url)
        return MCPServerSpec(
            name="pdf",
            command="uv",
            args=["run", "--directory", str(settings.pdf_path), "apollo-pdf-creator"],
            log_var="APOLLO_PDF_LOG_LEVEL",
            log_file="apollo-pdf-creator.log",
        )

    async def __aenter__(self) -> MCPRegistry:
        await super().__aenter__()
        for name, uri, attr in (
            ("chart", "charting://schema", "chart_schema"),
            ("pdf", "pdfcreator://schema", "pdf_schema"),
        ):
            if name not in self.toolsets_by_name:
                continue
            try:
                setattr(self, attr, await self.read_resource(name, uri))
            except Exception as exc:  # pragma: no cover - external servers
                self.errors[f"{name}:schema"] = f"{type(exc).__name__}: {exc}"
        return self

    @staticmethod
    def prefixed_tool_name(server: str, tool: str) -> str:
        return f"{server}_{tool}"
