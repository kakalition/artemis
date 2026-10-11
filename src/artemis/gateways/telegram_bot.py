"""aiogram v3 Telegram front-end (long-polling).

Chats are allowlisted via ``TELEGRAM_ALLOWED_CHAT_IDS``; each chat maps to a
conversation id ``tg:<chat_id>``. Bulk/destructive tool calls are approved with
inline buttons. Generated PNG/PDF artifacts are delivered as photos/documents.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

# Formatting + approval plumbing is generic and lives in agentkit.
from agentkit.gateways.telegram import (  # noqa: F401  (re-exported for tests)
    ApprovalBroker,
    _tg_entities,
    react_seen,
    run_turn,
    send_markdown,
)
from agentkit.gateways.telegram import is_allowed as _is_allowed_ids
from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, FSInputFile, Message

from artemis.config import Settings, build_model
from artemis.mcp.registry import MCPRegistry
from artemis.services.runtime import Runtime, build_deps, build_runtime, repositories
from artemis.services.session import ChatRunner


def is_allowed(settings: Settings, chat_id: int) -> bool:
    """Allow-list check bound to Artemis settings."""
    return _is_allowed_ids(settings.telegram_allowed_chat_ids, chat_id)


async def _deliver(bot: Bot, chat_id: int, artifacts: list[dict]) -> None:
    for artifact in artifacts:
        path = Path(str(artifact.get("path", "")))
        if not path.exists():
            continue
        photo = str(path).lower().endswith((".png", ".jpg", ".jpeg"))
        file = FSInputFile(str(path))
        with contextlib.suppress(Exception):
            if photo:
                await bot.send_photo(chat_id, file)
            else:
                await bot.send_document(chat_id, file)


async def handle_message(
    *,
    runtime: Runtime,
    registry: MCPRegistry | None,
    broker: ApprovalBroker,
    bot: Bot,
    chat_id: int,
    text: str,
    model: Any = None,
) -> None:
    """Run one chat turn and deliver the reply plus any artifacts."""
    from artemis.a2a.client import build_a2a_client

    conversation_id = f"tg:{chat_id}"
    with repositories(runtime) as repos:
        deps = build_deps(
            runtime,
            repos,
            model=model or build_model(runtime.settings),
            mcp=registry,
            a2a=build_a2a_client(runtime.settings),
            approve=lambda requests: broker.ask(bot, chat_id, requests),
        )
        runner = ChatRunner(deps, conversation_id=conversation_id)
        try:
            result = await runner.send(text)
        except Exception as exc:  # pragma: no cover - defensive
            await bot.send_message(chat_id, f"Something went wrong: {type(exc).__name__}")
            return
    await send_markdown(bot, chat_id, result.output)
    await _deliver(bot, chat_id, result.artifacts)


def register_handlers(
    dp: Dispatcher, runtime: Runtime, registry: MCPRegistry | None, broker: ApprovalBroker
) -> None:
    settings = runtime.settings

    @dp.message(F.text)
    async def _on_text(message: Message) -> None:
        chat_id = message.chat.id
        if not is_allowed(settings, chat_id):
            await message.answer("This bot is private.")
            return
        await react_seen(message, enabled=settings.telegram_seen_reaction)
        if message.text and message.text.strip().startswith("/start"):
            await message.answer("Artemis ready. Ask about your spending, budgets, goals or portfolio.")
            return
        if message.bot is None:
            return
        await run_turn(
            lambda: handle_message(
                runtime=runtime,
                registry=registry,
                broker=broker,
                bot=message.bot,
                chat_id=chat_id,
                text=message.text or "",
            ),
            bot=message.bot,
            chat_id=chat_id,
            live_status=settings.telegram_live_status,
            typing=settings.telegram_typing_action,
            phrase_interval_s=settings.telegram_status_interval_s,
        )

    @dp.callback_query(F.data.startswith("approve:"))
    async def _on_approve(callback: CallbackQuery) -> None:
        call_id = (callback.data or "").split(":", 1)[-1]
        broker.resolve(call_id, True)
        await callback.answer("Approved")
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)

    @dp.callback_query(F.data.startswith("deny:"))
    async def _on_deny(callback: CallbackQuery) -> None:
        call_id = (callback.data or "").split(":", 1)[-1]
        broker.resolve(call_id, False)
        await callback.answer("Denied")
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)


async def _run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    runtime = build_runtime(settings)
    registry = MCPRegistry(settings)
    broker = ApprovalBroker()
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    register_handlers(dp, runtime, registry, broker)
    async with registry:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)


def run_bot(settings: Settings) -> None:
    asyncio.run(_run_bot(settings))
