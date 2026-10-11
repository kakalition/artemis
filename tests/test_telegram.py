import asyncio

from artemis.config import Settings
from artemis.gateways.telegram_bot import (
    ApprovalBroker,
    _tg_entities,
    is_allowed,
    send_markdown,
)


class FakeBot:
    def __init__(self, fail_entities: bool = False) -> None:
        self.messages: list[tuple[str, dict]] = []
        self.fail_entities = fail_entities
        self._failed = False

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail_entities and not self._failed and kwargs.get("entities"):
            self._failed = True
            raise RuntimeError("bad entities")
        self.messages.append((text, kwargs))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.messages.append(("PHOTO", kwargs))

    async def send_document(self, chat_id, document, **kwargs):
        self.messages.append(("DOCUMENT", kwargs))


def test_is_allowed_empty_allowlist_allows_all():
    assert is_allowed(Settings(owner_id="owner"), 12345) is True


def test_is_allowed_enforced_when_configured():
    settings = Settings(owner_id="owner", telegram_allowed_chat_ids=[1, 2])
    assert is_allowed(settings, 1) is True
    assert is_allowed(settings, 3) is False


def test_tg_entities_maps_fields():
    class E:
        type = "bold"
        offset = 0
        length = 5
        url = None
        language = None
        custom_emoji_id = None
        unix_time = None
        date_time_format = None

    assert _tg_entities([]) is None
    mapped = _tg_entities([E()])
    assert mapped is not None
    assert mapped[0].type == "bold"
    assert mapped[0].length == 5


async def test_send_markdown_renders_bold():
    bot = FakeBot()
    await send_markdown(bot, 1, "**hello** world")
    assert len(bot.messages) == 1
    text, kwargs = bot.messages[0]
    assert "**" not in text
    assert "hello world" in text
    entities = kwargs.get("entities")
    assert entities and any(entity.type == "bold" for entity in entities)


async def test_send_markdown_splits_long_text():
    bot = FakeBot()
    await send_markdown(bot, 1, "\n\n".join(["line of text number"] * 600))
    assert len(bot.messages) > 1
    assert all(len(text) <= 4096 for text, _ in bot.messages)


async def test_send_markdown_falls_back_to_plain_text():
    bot = FakeBot(fail_entities=True)
    await send_markdown(bot, 1, "**bold** reply")
    # First attempt raised; the fallback re-sent as plain text.
    assert bot._failed is True
    assert any("bold reply" in text for text, _ in bot.messages)


def test_broker_resolve_unknown_is_noop():
    broker = ApprovalBroker()
    assert broker.resolve("missing", True) is False


async def test_broker_resolve_sets_future():
    broker = ApprovalBroker()
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    broker._pending["call-1"] = future
    assert broker.resolve("call-1", True) is True
    assert await future is True
    assert broker.resolve("call-1", False) is False
