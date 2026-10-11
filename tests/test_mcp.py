"""MCP tests.

The default tests use **in-process FastMCP servers** handed to ``MCPToolset`` —
no network, no subprocesses. The ``integration`` test spawns the real apollo
servers over stdio and self-skips when they are unavailable.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from artemis.agents.deps import Deps
from artemis.agents.reports import reports_agent
from artemis.config import Settings
from artemis.mcp.registry import MCPRegistry
from artemis.prices.base import ManualPriceSource


def _chart_server() -> FastMCP:
    server = FastMCP("chart")

    @server.tool
    def render_chart(spec: dict, force: bool = False) -> dict:
        """Render a chart to a PNG."""
        return {"out": "/tmp/chart.png", "bytes": 123, "force": force}

    @server.tool
    def validate_spec(spec: dict, strict: bool = False) -> dict:
        """Validate a chart spec."""
        return {"valid": True, "renderable": True}

    @server.resource("charting://schema")
    def schema() -> str:
        return "chart-schema"

    return server


def _pdf_server() -> FastMCP:
    server = FastMCP("pdf")

    @server.tool
    def create_pdf(spec: dict, force: bool = False) -> dict:
        """Create a PDF."""
        return {"out": "/tmp/report.pdf", "pages": 2, "force": force}

    @server.tool
    def validate_spec(spec: dict, strict: bool = False) -> dict:
        """Validate a document spec."""
        return {"valid": True}

    @server.resource("pdfcreator://schema")
    def schema() -> str:
        return "pdf-schema"

    return server


def _deps(repos, registry) -> Deps:
    return Deps(
        repos=repos,
        settings=Settings(owner_id="owner"),
        price_source=ManualPriceSource(),
        mcp=registry,
    )


def _name_capturing_model(captured: dict) -> FunctionModel:
    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        captured["names"] = {tool.name for tool in info.function_tools}
        return ModelResponse(parts=[TextPart("report ready")])

    return FunctionModel(model_fn)


async def test_registry_prefixes_and_reads_schema(repos):
    registry = MCPRegistry(
        Settings(owner_id="owner"),
        chart_client=_chart_server(),
        pdf_client=_pdf_server(),
    )
    async with registry:
        assert registry.chart_schema == "chart-schema"
        assert registry.pdf_schema == "pdf-schema"
        captured: dict = {}
        deps = _deps(repos, registry)
        deps.model = _name_capturing_model(captured)
        await reports_agent.run(
            "make a report", deps=deps, model=deps.model, toolsets=registry.toolsets()
        )
    assert {
        "chart_render_chart",
        "chart_validate_spec",
        "pdf_create_pdf",
        "pdf_validate_spec",
    } <= captured["names"]
    # The two `validate_spec` tools do not collide thanks to the prefixes.
    assert len([n for n in captured["names"] if n.endswith("validate_spec")]) == 2


async def test_registry_read_resource_tools(repos):
    registry = MCPRegistry(
        Settings(owner_id="owner"),
        chart_client=_chart_server(),
        pdf_client=_pdf_server(),
    )
    async with registry:
        deps = _deps(repos, registry)

        seen: dict = {}

        def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if any(
                getattr(part, "part_kind", "") == "tool-return"
                for message in messages
                for part in getattr(message, "parts", [])
            ):
                seen["schema"] = str(messages[-1].parts)
                return ModelResponse(parts=[TextPart("done")])
            return ModelResponse(parts=[_call("read_chart_schema", {})])

        from pydantic_ai.messages import ToolCallPart

        def _call(name, args):
            return ToolCallPart(name, args)

        await reports_agent.run(
            "fetch schema", deps=deps, model=FunctionModel(model_fn), toolsets=registry.toolsets()
        )
        assert "chart-schema" in seen.get("schema", "")


async def test_render_chart_returns_path(repos):
    registry = MCPRegistry(
        Settings(owner_id="owner"),
        chart_client=_chart_server(),
        pdf_client=_pdf_server(),
    )
    async with registry:
        deps = _deps(repos, registry)
        captured: dict = {}

        def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            names = {tool.name for tool in info.function_tools}
            captured["names"] = names
            if captured.get("called"):
                return ModelResponse(parts=[TextPart("done")])
            captured["called"] = True
            from pydantic_ai.messages import ToolCallPart

            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "chart_render_chart",
                        {"spec": {"chart": "bar", "title": "x", "data": []}, "force": True},
                    )
                ]
            )

        result = await reports_agent.run(
            "render", deps=deps, model=FunctionModel(model_fn), toolsets=registry.toolsets()
        )
        assert result.output == "done"


@pytest.mark.integration
async def test_real_apollo_servers_stdio():
    settings = Settings(owner_id="owner")
    if not settings.charting_path.exists():
        pytest.skip("apollo-charting not present")
    registry = MCPRegistry(settings)
    try:
        async with asyncio.timeout(120):
            async with registry:
                if not registry.available:
                    pytest.skip(f"apollo servers unavailable: {registry.errors}")
                names = await registry.tool_names()
    except (TimeoutError, Exception) as exc:  # noqa: BLE001
        pytest.skip(f"apollo servers not runnable here: {type(exc).__name__}: {exc}")
    assert any("render_chart" in n for n in names)
