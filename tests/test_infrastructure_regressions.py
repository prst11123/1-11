"""Offline transport/startup regressions: no live Telegram credentials or calls."""
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from app.config import Settings
from app.main import CONFIG_KEY, HANDLER_KEY, READY_KEY, STORE_KEY, TELEGRAM_KEY, startup, webhook
from app.telegram import Telegram, TelegramError


@pytest.mark.asyncio
@pytest.mark.parametrize("response_body", ["<html>Bad gateway</html>", "[]", "null", '{"result":{}}'])
async def test_ambiguous_send_response_is_not_retried(response_body):
    requests = []

    async def receive(request):
        requests.append(request.path)
        return web.Response(text=response_body, content_type="application/json", status=502)

    app = web.Application()
    app.router.add_post("/sendMessage", receive)
    async with TestServer(app) as server:
        tg = Telegram("test-token")
        await tg.start()
        tg._base = str(server.make_url("/"))
        try:
            with pytest.raises(TelegramError) as err:
                await tg.send_message(123, "DEMO")
            assert err.value.status == 0
            assert requests == ["/sendMessage"]
        finally:
            await tg.close()


@pytest.mark.asyncio
async def test_transport_exception_traceback_does_not_expose_request_token():
    sentinel = "TEST_SENTINEL_TOKEN_NEVER_LOG"
    error = aiohttp.ClientResponseError(
        request_info=SimpleNamespace(real_url=f"https://api.telegram.org/bot{sentinel}/sendMessage"),
        history=(), status=502, message="Bad gateway")
    tg = Telegram(sentinel)
    tg._session = SimpleNamespace(post=Mock(side_effect=error))
    with pytest.raises(TelegramError) as err:
        await tg.send_message(123, "DEMO")
    assert sentinel not in "".join(traceback.format_exception(err.type, err.value, err.tb))
    assert tg._session.post.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["sendMessage", "editMessageMedia", "answerGuestQuery"])
@pytest.mark.parametrize("http_status", [200, 500, 502])
async def test_json_server_error_is_ambiguous_not_a_safe_fallback(method, http_status):
    requests = []

    async def receive(request):
        requests.append(request.path)
        return web.json_response({"ok": False, "error_code": 500, "description": "Internal server error"},
                                 status=http_status)

    app = web.Application()
    app.router.add_post("/" + method, receive)
    async with TestServer(app) as server:
        tg = Telegram("test-token")
        await tg.start()
        tg._base = str(server.make_url("/"))
        try:
            with pytest.raises(TelegramError) as err:
                await tg.api(method)
            assert err.value.status == 0
            assert requests == ["/" + method]
        finally:
            await tg.close()


@pytest.mark.asyncio
async def test_uploaded_image_overrides_stale_document_file_id():
    tg = Telegram("test-token")
    tg.api = AsyncMock(return_value={"message_id": 10})
    await tg.send_media(123, "old_document", "document", "DEMO", image_data=b"JPEG")
    args, fields = tg.api.call_args
    assert args == ("sendPhoto",)
    assert fields["__upload"][0] == "photo"
    assert "document" not in fields


@pytest.mark.asyncio
async def test_inline_text_edit_keeps_nft_preview():
    tg = Telegram("test-token")
    tg.api = AsyncMock(return_value=True)
    await tg.edit_inline_offer("inline1", "https://t.me/nft/InputKey-25057", {}, False)
    assert tg.api.call_args.kwargs["link_preview_options"] == {"prefer_large_media": True}


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_auth_and_update_shape(config):
    handler = SimpleNamespace(dispatch=AsyncMock())
    app = web.Application()
    app[CONFIG_KEY] = config
    app[HANDLER_KEY] = handler
    app[READY_KEY] = True
    app.router.add_post("/telegram/webhook", webhook)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/telegram/webhook", json={"update_id": 1},
                                     headers={"X-Telegram-Bot-Api-Secret-Token": "не-секрет"})
        assert response.status == 403
        for payload in ({}, {"update_id": True}, {"update_id": -1}, {"update_id": "1"}, []):
            response = await client.post("/telegram/webhook", json=payload,
                                         headers={"X-Telegram-Bot-Api-Secret-Token": config.webhook_secret})
            assert response.status == 400
        handler.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_startup_closes_network_and_database(config):
    store = SimpleNamespace(initialize_admins=Mock(), db=SimpleNamespace(close=Mock()))
    tg = SimpleNamespace(start=AsyncMock(), close=AsyncMock(), api=AsyncMock(side_effect=RuntimeError("unavailable")))
    app = {CONFIG_KEY: config, STORE_KEY: store, TELEGRAM_KEY: tg}
    with pytest.raises(RuntimeError, match="unavailable"):
        await startup(app)
    tg.close.assert_awaited_once()
    store.db.close.assert_called_once()


@pytest.mark.parametrize("url", ["https://example.com/telegram/webhook", "https://user:pass@example.com",
                                  "https://example.com:1234", "https://example.com:bad", "https://bad host"])
def test_webhook_config_rejects_unreachable_endpoint_shapes(config, url):
    values = config.model_dump(by_alias=True)
    values["WEBHOOK_URL"] = url
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_default_nft_url_is_validated_at_startup(config):
    values = config.model_dump(by_alias=True)
    values["DEFAULT_GIFT_URL"] = "https://example.com/not-an-nft"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_validation_traceback_hides_secret_input_even_during_migrations(config):
    values = config.model_dump(by_alias=True)
    sentinel = "INVALID_SECRET_MUST_NOT_APPEAR"
    values["BOT_TOKEN"] = sentinel
    with pytest.raises(ValidationError) as err:
        Settings(_env_file=None, **values)
    assert sentinel not in str(err.value)
