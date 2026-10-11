"""Artemis as an A2A server (``artemis a2a``), built on the official ``a2a-sdk``.

The executor answers with a single agent ``Message`` (the SDK's "immediate
response" workflow), delegating the actual work to the Artemis orchestrator via
:class:`A2ABridge`.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from a2a import types as t
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import TaskUpdater
from agentkit.a2a.task_store import SQLAlchemyTaskStore
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from artemis.a2a.client import A2AClient, build_a2a_client
from artemis.config import Settings, build_model
from artemis.mcp.registry import MCPRegistry
from artemis.services.runtime import Runtime, build_deps, build_runtime, repositories
from artemis.services.session import ChatRunner

A2A_CONVERSATION_ID = "a2a:default"


class A2ABridge:
    """Runs the orchestrator for one A2A request and returns the reply text."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        registry: MCPRegistry | None = None,
        a2a_client: A2AClient | None = None,
        model: Any = None,
        conversation_id: str = A2A_CONVERSATION_ID,
    ) -> None:
        self.runtime = runtime
        self.registry = registry
        self.a2a_client = a2a_client
        self.model = model or build_model(runtime.settings)
        self.conversation_id = conversation_id

    async def answer(self, text: str) -> str:
        with repositories(self.runtime) as repos:
            deps = build_deps(
                self.runtime,
                repos,
                model=self.model,
                mcp=self.registry,
                a2a=self.a2a_client,
            )
            runner = ChatRunner(deps, conversation_id=self.conversation_id)
            result = await runner.send(text)
        output = result.output
        if result.artifacts:
            lines = [f"- {a['kind']}: {a['path']}" for a in result.artifacts]
            output = f"{output}\n\nArtifacts:\n" + "\n".join(lines)
        return output


class FinanceAgentExecutor(AgentExecutor):
    """A2A executor that answers with one agent message."""

    def __init__(self, bridge: A2ABridge) -> None:
        self._bridge = bridge

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Task-based flow: the SDK requires a Task event before any status
        # update, so enqueue the initial Task, then drive it through
        # working -> completed (or failed) with an artifact carrying the reply.
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or ""
        await event_queue.enqueue_event(
            t.Task(
                id=task_id,
                context_id=context_id,
                status=t.TaskStatus(state=t.TaskState.TASK_STATE_SUBMITTED),
            )
        )
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.start_work()
        try:
            text = await self._bridge.answer(context.get_user_input())
        except Exception as exc:  # surface failure as a failed task
            await updater.failed(
                message=t.Message(
                    message_id=str(uuid.uuid4()),
                    role=t.Role.ROLE_AGENT,
                    parts=[t.Part(text=f"error: {type(exc).__name__}")],
                    task_id=task_id,
                    context_id=context_id,
                )
            )
            return
        await updater.add_artifact([t.Part(text=text)], name="result")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def build_card(settings: Settings) -> t.AgentCard:
    return t.AgentCard(
        name=settings.a2a_card_name,
        description=(
            "Artemis — a personal finance agent (expenses, budgets, goals, portfolio, "
            "insights). Educational guidance, not regulated advice."
        ),
        version="1.0.0",
        supported_interfaces=[
            t.AgentInterface(
                url=settings.a2a_public_url,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/markdown", "application/pdf", "image/png"],
        capabilities=t.AgentCapabilities(),
        skills=[
            t.AgentSkill(
                id="personal-finance",
                name="Personal finance",
                description="Track expenses, budgets, savings goals, portfolio, and spending insights.",
                tags=["finance", "budgeting", "ledger", "investing"],
            )
        ],
    )


def build_app(
    settings: Settings,
    *,
    runtime: Runtime | None = None,
    registry: MCPRegistry | None = None,
    a2a_client: A2AClient | None = None,
    model: Any = None,
) -> Starlette:
    runtime = runtime or build_runtime(settings)
    a2a_client = a2a_client or build_a2a_client(settings)
    card = build_card(settings)
    bridge = A2ABridge(runtime, registry=registry, a2a_client=a2a_client, model=model)
    handler = DefaultRequestHandler(
        agent_executor=FinanceAgentExecutor(bridge),
        task_store=SQLAlchemyTaskStore(runtime),
        agent_card=card,
    )
    async def healthz(request: Any) -> JSONResponse:
        try:
            with repositories(runtime) as repos:
                repos.transactions.count()
        except Exception as exc:  # pragma: no cover - defensive
            return JSONResponse({"status": "error", "db": str(exc)}, status_code=503)
        return JSONResponse({"status": "ok", "db": "ok"})

    routes = (
        [Route("/healthz", healthz)]
        + create_agent_card_routes(card)
        + create_jsonrpc_routes(handler, "/")
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        if registry is not None:
            async with registry:
                yield
        else:
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def serve(settings: Settings) -> None:
    from artemis.guardrails import warn_if_exposed

    runtime = build_runtime(settings)
    registry = MCPRegistry(settings)
    app = build_app(settings, runtime=runtime, registry=registry)
    warn_if_exposed(settings.a2a_host, "the Artemis A2A server")
    uvicorn.run(app, host=settings.a2a_host, port=settings.a2a_port)
