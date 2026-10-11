"""Conversation history + chat runner (agentkit), defaulting to Artemis' orchestrator."""

from __future__ import annotations

from typing import Any

from agentkit.session import (  # noqa: F401  # noqa: F401
    DEFAULT_MAX_HISTORY,
    ChatResult,
    deserialize_messages,
    load_history,
    save_new_messages,
    serialize_message,
)
from agentkit.session import ChatRunner as _ChatRunner

from artemis.agents.deps import Deps

__all__ = [
    "ChatRunner",
    "ChatResult",
    "DEFAULT_MAX_HISTORY",
    "load_history",
    "save_new_messages",
    "serialize_message",
    "deserialize_messages",
]


class ChatRunner(_ChatRunner):
    """agentkit runner that defaults to the Artemis orchestrator agent."""

    def __init__(
        self,
        deps: Deps,
        *,
        agent: Any = None,
        conversation_id: str = "cli:default",
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        if agent is None:
            from artemis.agents.orchestrator import orchestrator_agent

            agent = orchestrator_agent
        super().__init__(
            deps, agent=agent, conversation_id=conversation_id, max_history=max_history
        )
