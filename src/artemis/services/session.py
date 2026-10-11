"""Conversation history persistence and the chat runner.

Message history is stored in libSQL via PydanticAI's
``ModelMessagesTypeAdapter``, keyed by a conversation id (``cli:default``,
``tg:<chat_id>``). This is what makes history survive restarts and move between
channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from artemis.agents.deps import Deps
from artemis.db.repos import Repositories

DEFAULT_MAX_HISTORY = 40


def serialize_message(message: ModelMessage) -> str:
    return ModelMessagesTypeAdapter.dump_json([message]).decode()


def deserialize_messages(payloads: list[str]) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for payload in payloads:
        messages.extend(ModelMessagesTypeAdapter.validate_json(payload))
    return messages


def load_history(
    repos: Repositories, conversation_id: str, *, max_messages: int = DEFAULT_MAX_HISTORY
) -> list[ModelMessage]:
    payloads = [m.payload for m in repos.messages.list(conversation_id)]
    if max_messages and len(payloads) > max_messages:
        payloads = payloads[-max_messages:]
    return deserialize_messages(payloads)


def save_new_messages(
    repos: Repositories, conversation_id: str, messages: list[ModelMessage], start_index: int
) -> int:
    new_messages = messages[start_index:]
    if not new_messages:
        return 0
    return repos.messages.append(conversation_id, [serialize_message(m) for m in new_messages])


@dataclass
class ChatResult:
    output: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    history_length: int = 0


class ChatRunner:
    """Runs the orchestrator against one conversation and persists history."""

    def __init__(
        self,
        deps: Deps,
        *,
        conversation_id: str = "cli:default",
        agent: Agent[Any, str] | None = None,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self.deps = deps
        self.conversation_id = conversation_id
        self.max_history = max_history
        if agent is None:
            from artemis.agents.orchestrator import orchestrator_agent

            agent = orchestrator_agent
        self.agent = agent

    async def send(self, text: str) -> ChatResult:
        repos = self.deps.repos
        channel = self.conversation_id.split(":", 1)[0]
        repos.conversations.get_or_create(self.conversation_id, channel=channel)
        history = load_history(repos, self.conversation_id, max_messages=self.max_history)

        self.deps.artifacts.clear()
        result = await self.agent.run(
            text,
            deps=self.deps,
            message_history=history,
            model=self.deps.model,
        )
        all_messages = result.all_messages()
        save_new_messages(repos, self.conversation_id, all_messages, start_index=len(history))
        repos.conversations.touch(self.conversation_id)
        return ChatResult(
            output=result.output if isinstance(result.output, str) else str(result.output),
            artifacts=list(self.deps.artifacts),
            history_length=len(all_messages),
        )

    def reset(self) -> None:
        self.deps.repos.messages.clear(self.conversation_id)
