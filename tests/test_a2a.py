"""A2A tests using the official a2a-sdk client against an in-process server."""

from __future__ import annotations

import httpx
from a2a import types as t
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from artemis.a2a.client import A2AClient, _texts_from, load_peers
from artemis.a2a.server import build_app, build_card
from artemis.config import Settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.services.runtime import Runtime

BASE = "http://test"


def _runtime(tmp_path) -> Runtime:
    engine = create_db_engine(f"sqlite+libsql:///{tmp_path / 'artemis.db'}")
    bootstrap(engine, "owner", "Owner")
    return Runtime(
        settings=Settings(owner_id="owner", a2a_public_url=BASE, artemis_home=tmp_path),
        engine=engine,
        session_factory=make_session_factory(engine),
    )


def _text_model() -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("a2a hello")])

    return FunctionModel(fn)


def _texts_model(text: str):
    return FunctionModel(lambda m, i: ModelResponse(parts=[TextPart(text)]))


def test_build_card(tmp_path):
    card = build_card(_runtime(tmp_path).settings)
    assert card.name == "Artemis"
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.skills[0].id == "personal-finance"


async def test_client_roundtrip_against_inproc_server(tmp_path):
    runtime = _runtime(tmp_path)
    app = build_app(
        runtime.settings,
        runtime=runtime,
        registry=None,
        a2a_client=A2AClient(),
        model=_text_model(),
    )
    client = A2AClient(transport=httpx.ASGITransport(app=app))

    card = await client.fetch_card(BASE)
    assert card.name == "Artemis"

    reply = await client.call_agent(BASE, "hi")
    assert reply == "a2a hello"


def test_texts_from_stream_response():
    task_response = t.StreamResponse(
        task=t.Task(artifacts=[t.Artifact(parts=[t.Part(text="from artifact")])])
    )
    assert _texts_from(task_response) == ["from artifact"]

    message_response = t.StreamResponse(
        message=t.Message(parts=[t.Part(text="from message")])
    )
    assert _texts_from(message_response) == ["from message"]


def test_load_peers(tmp_path):
    peers_file = tmp_path / "peers.json"
    peers_file.write_text('{"peers": {"research": {"url": "http://x:9100", "token": "t"}}}')
    settings = Settings(owner_id="owner", peers_file=str(peers_file))
    peers = load_peers(settings)
    assert peers["research"].url == "http://x:9100"
    assert peers["research"].token == "t"
