from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from app.handlers import AppHandler
from app.telegram import TelegramError


@pytest.mark.asyncio
async def test_diag_refreshes_botfather_flags_without_restart(config, store):
    flags = {"username": "uuuuu11_bot", "supports_guest_queries": False,
             "supports_inline_queries": True}
    async def api(method):
        return flags if method == "getMe" else {"url": config.webhook_endpoint}
    bot = SimpleNamespace(api=api, send_message=AsyncMock())
    handler = AppHandler(config, store, bot)
    message = {"chat": {"id": 1001, "type": "private"}, "from": {"id": 1001}, "text": "/diag"}
    await handler.on_message(message)
    assert "Guest Mode: ⚠️ выключен" in bot.send_message.call_args.args[1]
    assert "Inline Mode: ✅ включён" in bot.send_message.call_args.args[1]
    flags["supports_guest_queries"] = True
    await handler.on_message(message)
    assert "Guest Mode: ✅ включён" in bot.send_message.call_args.args[1]
    assert handler.guest_enabled


@pytest.mark.asyncio
async def test_diag_does_not_present_cached_guest_flag_as_live(config, store):
    async def api(method):
        if method == "getMe":
            raise TelegramError(method, 0, "timeout")
        return {"url": config.webhook_endpoint}
    bot = SimpleNamespace(api=api, send_message=AsyncMock())
    handler = AppHandler(config, store, bot)
    handler.guest_enabled = True
    await handler.on_message({"chat": {"id": 1001, "type": "private"},
                              "from": {"id": 1001}, "text": "/diag"})
    assert "Guest Mode: ⚠️ не удалось проверить" in bot.send_message.call_args.args[1]


@pytest.mark.asyncio
async def test_share_explains_official_inline_fallback_when_guest_disabled(config, store):
    bot = SimpleNamespace(api=AsyncMock(return_value={"username": "uuuuu11_bot",
                          "supports_guest_queries": False}), send_message=AsyncMock())
    handler = AppHandler(config, store, bot)
    await handler.on_message({"chat": {"id": 1001, "type": "private"},
                              "from": {"id": 1001}, "text": "/share"})
    assert "Guest Mode по последней проверке выключен" in bot.send_message.call_args.args[1]
    assert "выберите DEMO-результат" in bot.send_message.call_args.args[1]
    assert "switch_inline_query" in str(bot.send_message.call_args.args[2])
