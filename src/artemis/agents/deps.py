"""Typed dependencies shared by every agent run."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from artemis.config import Settings
from artemis.db.repos import Repositories
from artemis.prices.base import PriceSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    from artemis.a2a.client import A2AClient
    from artemis.mcp.registry import MCPRegistry


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class ApprovalRequest:
    """A pending tool call awaiting the owner's approval."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


ApprovalCallback = Callable[[list[ApprovalRequest]], Awaitable[dict[str, bool]]]


@dataclass
class Deps:
    """Everything an agent tool might need, passed through ``RunContext``."""

    owner_id: str
    repos: Repositories
    settings: Settings
    price_source: PriceSource
    mcp: MCPRegistry | None = None
    a2a: A2AClient | None = None
    model: Any = None
    approve: ApprovalCallback | None = None
    clock: Any = field(default=_now)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def now(self) -> datetime:
        return self.clock()

    def remember_artifact(self, kind: str, path: str, description: str = "") -> None:
        self.artifacts.append({"kind": kind, "path": path, "description": description})
