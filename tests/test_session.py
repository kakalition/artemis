from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from artemis.agents.deps import Deps
from artemis.config import Settings
from artemis.prices.base import ManualPriceSource
from artemis.services.session import ChatRunner, deserialize_messages, load_history


def _text_model(text: str) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(fn)


def _deps(repos) -> Deps:
    return Deps(
        owner_id="owner",
        repos=repos,
        settings=Settings(owner_id="owner"),
        price_source=ManualPriceSource(),
    )


async def test_chat_runner_roundtrip_with_model(repos):
    deps = _deps(repos)
    deps.model = _text_model("hi there")
    runner = ChatRunner(deps, conversation_id="cli:default")
    first = await runner.send("hello")
    assert first.output == "hi there"
    assert first.history_length == 2

    # A brand-new runner on the same conversation sees the history.
    deps2 = _deps(repos)
    deps2.model = _text_model("again")
    runner2 = ChatRunner(deps2, conversation_id="cli:default")
    second = await runner2.send("more")
    assert second.history_length == 4


def test_history_serialization_roundtrip(repos):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    message = ModelRequest(parts=[UserPromptPart(content="remember this")])
    from artemis.services.session import serialize_message

    payloads = [serialize_message(message)]
    restored = deserialize_messages(payloads)
    assert len(restored) == 1
    assert restored[0].parts[0].content == "remember this"

    repos.conversations.get_or_create("cli:default")
    repos.messages.append("cli:default", payloads)
    assert len(load_history(repos, "cli:default")) == 1
