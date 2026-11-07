"""Validate direct official Bot API field shapes against a local fake HTTP endpoint."""
import json
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest
from app.telegram import Telegram, TelegramError


@pytest.mark.asyncio
async def test_send_photo_multipart_and_business_connection():
    sent=[]

    async def receive(request):
        assert request.path.endswith("/sendPhoto")
        reader=await request.multipart()
        data={}
        async for part in reader:
            if part.name=="photo":
                data["photo_bytes"]=await part.read()
            else:
                data[part.name]=await part.text()
        sent.append(data)
        return web.json_response({"ok":True,"result":{"message_id":777}})

    app=web.Application()
    app.router.add_post("/botFAKE/sendPhoto",receive)
    async with TestServer(app) as server:
        tg=Telegram("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456789")
        await tg.start()
        tg._base=str(server.make_url("/botFAKE/"))
        response=await tg.send_media(2002,None,"photo","DEMO Gift",{"inline_keyboard":[[{"text":"Принять","callback_data":"offer:accept:9"}]]},"b_test")
        await tg.close()
    assert response["message_id"]==777
    assert len(sent)==1
    assert sent[0]["business_connection_id"]=="b_test"
    assert sent[0]["chat_id"]=="2002"
    assert sent[0]["photo_bytes"].startswith(b"\x89PNG")
    assert json.loads(sent[0]["reply_markup"])["inline_keyboard"][0][0]["callback_data"]=="offer:accept:9"


@pytest.mark.asyncio
async def test_api_error_is_not_success():
    async def reject(request):
        return web.json_response({"ok":False,"error_code":403,"description":"Forbidden"},status=403)

    app=web.Application()
    app.router.add_post("/botFAKE/sendMessage",reject)
    async with TestServer(app) as server:
        tg=Telegram("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456789")
        await tg.start()
        tg._base=str(server.make_url("/botFAKE/"))
        with pytest.raises(TelegramError) as exc:
            await tg.send_message(2002,"Hello",business_id="b_test")
        await tg.close()
    assert exc.value.status==403


@pytest.mark.asyncio
@pytest.mark.parametrize("code,description", [(400, "Bad Request: PEER_FLOOD"), (429, "Too Many Requests")])
async def test_delivery_flood_response_is_not_retried(code, description):
    requests = []
    async def reject(request):
        requests.append(request.path)
        return web.json_response({"ok": False, "error_code": code, "description": description,
                                  "parameters": {"retry_after": 30}}, status=code)
    app = web.Application()
    app.router.add_post("/test/sendMessage", reject)
    async with TestServer(app) as server:
        tg = Telegram("unused")
        await tg.start()
        tg._base = str(server.make_url("/test/"))
        try:
            with pytest.raises(TelegramError) as exc:
                await tg.send_message(2002, "DEMO", business_id="test")
        finally:
            await tg.close()
    assert len(requests) == 1
    assert exc.value.is_flood
    assert exc.value.delivery_hint
