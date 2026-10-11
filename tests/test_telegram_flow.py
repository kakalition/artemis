"""End-to-end Telegram handler test with a stub bot and a FunctionModel."""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from artemis.config import Settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.gateways.telegram_bot import ApprovalBroker, handle_message
from artemis.services.runtime import Runtime


class StubBot:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):  # noqa: ANN001
        self.messages.append(text)

    async def send_photo(self, chat_id, photo, **kwargs):  # noqa: ANN001
        self.messages.append("PHOTO")

    async def send_document(self, chat_id, document, **kwargs):  # noqa: ANN001
        self.messages.append("DOCUMENT")


def _runtime(tmp_path) -> Runtime:
    engine = create_db_engine(f"sqlite+libsql:///{tmp_path / 'artemis.db'}")
    bootstrap(engine, "owner", "Owner")
    return Runtime(
        settings=Settings(owner_id="owner", agent_home=tmp_path),
        engine=engine,
        session_factory=make_session_factory(engine),
    )


async def test_handle_message_replies_and_formats(tmp_path):
    runtime = _runtime(tmp_path)
    bot = StubBot()
    model = FunctionModel(
        lambda messages, info: ModelResponse(parts=[TextPart("**hello** from artemis")])
    )
    await handle_message(
        runtime=runtime,
        registry=None,
        broker=ApprovalBroker(),
        bot=bot,  # type: ignore[arg-type]
        chat_id=42,
        text="hi",
        model=model,
    )
    assert bot.messages, "expected a reply"
    # Markdown bold is rendered to entities, so the plain text has no '*'.
    assert "hello from artemis" in bot.messages[0]
    assert "*" not in bot.messages[0]


async def test_handle_message_persists_history(tmp_path):
    runtime = _runtime(tmp_path)
    bot = StubBot()
    model = FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("ok")]))
    await handle_message(
        runtime=runtime,
        registry=None,
        broker=ApprovalBroker(),
        bot=bot,  # type: ignore[arg-type]
        chat_id=7,
        text="first",
        model=model,
    )
    from sqlmodel import Session

    from artemis.db.repos import Repositories

    with Session(runtime.engine) as session:
        repos = Repositories(session, "owner")
        assert repos.messages.list("tg:7")
