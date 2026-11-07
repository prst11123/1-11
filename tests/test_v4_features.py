"""V4: edit-first transport, safe cleanup, inline delivery, and private diagnostics."""
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.handlers import AppHandler
from app.db import Database
from app.models import Base
from app.store import Store, DomainError
from app.telegram import Telegram, TelegramError
from app import keyboards as kb
from app import render as rnd


@pytest.fixture
def v4_store(config, tmp_path):
    db=Database("sqlite:///"+str(tmp_path/"v4.db"))
    Base.metadata.create_all(db.engine)
    store=Store(db,config)
    store.initialize_admins()
    yield store
    db.close()


class EditingTelegram:
    def __init__(self, edit_error=None, delete_allowed=True):
        self.remote={"id":"biz-v4","user":{"id":1001},"is_enabled":True,
                     "rights":{"can_reply":True,"can_delete_all_messages":delete_allowed}}
        self.edit_error=edit_error
        self.operations=[]
        self.notifications=[]

    async def get_business_connection(self, cid):
        assert cid=="biz-v4"
        return self.remote

    async def edit_business_offer(self,chat_id,message_id,business_id,source_kind,
                                  image_data,image_file_id,caption,markup):
        self.operations.append(("edit",chat_id,message_id,business_id,source_kind,image_data))
        assert "DEMO" in caption and "A/X T" not in caption
        if self.edit_error:
            raise self.edit_error
        return {"message_id":message_id,"photo":[{"file_id":"edited-photo"}]}

    async def send_media(self,chat_id,image_file_id,media_kind,caption,markup=None,business_id=None,
                         image_data=None,reply_to_message_id=None):
        self.operations.append(("send",chat_id,reply_to_message_id,business_id))
        assert "DEMO" in caption
        return {"message_id":9000,"photo":[{"file_id":"sent-photo"}]}

    async def delete_business_source(self,conn,message_id):
        self.operations.append(("delete",conn,message_id))

    async def send_message(self,chat_id,text,markup=None,business_id=None):
        self.notifications.append((chat_id,text))
        return {"message_id":90}


async def setup_business(store, bot):
    store.connection_update(bot.remote)
    now=int(datetime.now(timezone.utc).timestamp())
    store.business_incoming({"business_connection_id":"biz-v4","message_id":10,"date":now,
                             "chat":{"type":"private","id":2002},
                             "from":{"id":2002,"first_name":"Tester"}})
    return {"business_connection_id":"biz-v4","message_id":11,"date":now,
            "chat":{"type":"private","id":2002},"from":{"id":1001},
            "text":"https://t.me/nft/PlushPepe-123\n1000\n15м"}


@pytest.mark.asyncio
async def test_successful_business_edit_replaces_outbound_message(v4_store,config,monkeypatch):
    bot=EditingTelegram()
    msg=await setup_business(v4_store,bot)
    async def jpeg(_):return b"jpeg"
    monkeypatch.setattr("app.handlers.fetch_gift_image",jpeg)
    h=AppHandler(config,v4_store,bot)
    await h.dispatch({"update_id":11001,"business_message":msg})
    assert [op[0] for op in bot.operations]==["edit"]
    assert bot.operations[0][2]==11
    o=v4_store.offers_by_creator(1001)[1][0]
    assert (o.telegram_message_id,o.status,o.delivery_status,o.gift_image_file_id)==(11,"active","sent","edited-photo")
    await h.dispatch({"update_id":11002,"business_message":msg})
    assert [op[0] for op in bot.operations]==["edit"]  # idempotent even with new update_id


@pytest.mark.asyncio
async def test_edit_rejected_fallback_then_delete_only_with_rights(v4_store,config,monkeypatch):
    bot=EditingTelegram(edit_error=TelegramError("editMessageMedia",400,"message can't be edited"))
    msg=await setup_business(v4_store,bot)
    async def jpeg(_):return b"jpeg"
    monkeypatch.setattr("app.handlers.fetch_gift_image",jpeg)
    await AppHandler(config,v4_store,bot).dispatch({"update_id":11003,"business_message":msg})
    assert [op[0] for op in bot.operations]==["edit","send","delete"]
    assert v4_store.offers_by_creator(1001)[1][0].telegram_message_id==9000


@pytest.mark.asyncio
async def test_no_delete_without_permission(v4_store,config,monkeypatch):
    bot=EditingTelegram(edit_error=TelegramError("editMessageMedia",403,"Forbidden"),delete_allowed=False)
    msg=await setup_business(v4_store,bot)
    async def jpeg(_):return b"jpeg"
    monkeypatch.setattr("app.handlers.fetch_gift_image",jpeg)
    await AppHandler(config,v4_store,bot).dispatch({"update_id":11004,"business_message":msg})
    assert [op[0] for op in bot.operations]==["edit","send"]


@pytest.mark.asyncio
async def test_uncertain_edit_never_duplicates_or_deletes(v4_store,config,monkeypatch):
    bot=EditingTelegram(edit_error=TelegramError("editMessageMedia",0,"timeout"))
    msg=await setup_business(v4_store,bot)
    async def jpeg(_):return b"jpeg"
    monkeypatch.setattr("app.handlers.fetch_gift_image",jpeg)
    await AppHandler(config,v4_store,bot).dispatch({"update_id":11005,"business_message":msg})
    assert [op[0] for op in bot.operations]==["edit"]
    assert v4_store.offers_by_creator(1001)[1][0].delivery_status=="unknown"


class InlineTelegram:
    def __init__(self):
        self.answers=[]
        self.edits=[]
        self.alerts=[]
        self.media=[]
        self.messages=[]
    async def send_message(self, chat_id, text, markup=None, business_id=None):
        self.messages.append((chat_id, text, markup))
        return {"message_id":890}
    async def answer_inline(self,id_,results):
        self.answers.append(results)
    async def edit_inline_offer(self,inline_message_id,text,markup,photo):
        self.edits.append((inline_message_id,text,markup,photo))
    async def answer_callback(self,id_,text="",alert=False):
        self.alerts.append((id_,text,alert))
    async def send_media(self,*args,**kwargs):
        self.media.append((args,kwargs))
        return {"message_id":889}
    async def edit_test_caption(self,chat_id,message_id,caption,markup):
        self.edits.append((chat_id, message_id, caption, markup))


@pytest.mark.asyncio
async def test_inline_in_any_chat_with_independent_statuses(v4_store,config):
    bot=InlineTelegram()
    h=AppHandler(config,v4_store,bot)
    await h.dispatch({"update_id":11006,"inline_query":{"id":"IQ1", "from":{"id":1001},
                     "query":"https://t.me/nft/InputKey-25057 1200 30"}})
    assert len(bot.answers)==1
    article,photo=bot.answers[-1]
    assert article["type"]=="article"
    assert photo["type"]=="photo"
    assert "InputKey #25057" in photo["caption"]
    assert "DEMO" in article["input_message_content"]["message_text"]
    offer_id=int(photo["id"][1:-1])
    assert photo["reply_markup"]["inline_keyboard"][0][1]["callback_data"]==f"inline:accept:{offer_id}:p"
    # A second person can accept this independently in another selected inline chat.
    callback={"id":"cb-one","from":{"id":2002},"inline_message_id":"msg-one",
              "data":f"inline:accept:{offer_id}:p"}
    await h.dispatch({"update_id":11007,"callback_query":callback})
    assert bot.edits[-1][3] is True
    assert "Принят" in bot.edits[-1][1]
    callback2={"id":"cb-two","from":{"id":2003},"inline_message_id":"msg-two",
               "data":f"inline:decline:{offer_id}:t"}
    await h.dispatch({"update_id":11008,"callback_query":callback2})
    assert bot.edits[-1][3] is False
    assert "Отклонён" in bot.edits[-1][1]
    # A legacy transfer callback must not initiate a gift movement or change status.
    await h.dispatch({"update_id":11009,"callback_query":{
        "id":"cb-three","from":{"id":2002},"inline_message_id":"msg-one",
        "data":f"inline:transfer:{offer_id}:p"}})
    assert "Отклонён" in bot.edits[-1][1]  # no new edit was made
    assert "DEMO" in bot.alerts[-1][1]
    assert "A/X" not in bot.edits[-1][1]
    assert v4_store.inline_action(offer_id,"msg-two","instructions")[1]=="declined"


@pytest.mark.asyncio
async def test_inline_unrecognized_and_unauthorized_requests_are_empty(v4_store,config):
    bot=InlineTelegram()
    h=AppHandler(config,v4_store,bot)
    for i, (user, query) in enumerate(((1001,"hi"),(31337,"https://t.me/nft/InputKey-25057 100 5"))):
        await h.dispatch({"update_id":12000+i,"inline_query":{"id":f"q{i}","from":{"id":user},"query":query}})
    assert bot.answers==[[],[]]


@pytest.mark.asyncio
async def test_private_self_test_and_buttons(v4_store,config):
    bot=InlineTelegram()
    h=AppHandler(config,v4_store,bot)
    await h.dispatch({"update_id":12010,"message":{
        "chat":{"type":"private","id":1001},"from":{"id":1001},"text":"/test"}})
    assert len(bot.media)==1
    (args,_) = bot.media[-1]
    assert "DEMO" in args[3]
    assert "A/X" not in args[3]
    await h.dispatch({"update_id":12011,"callback_query":{
        "from":{"id":1001},"id":"test-cb-1","data":"test:accept",
        "message":{"message_id":889,"chat":{"type":"private","id":1001}}}})
    assert "Принят" in bot.edits[-1][2]
    await h.dispatch({"update_id":12012,"callback_query":{
        "from":{"id":1001},"id":"test-cb-2","data":"test:instructions",
        "message":{"message_id":889,"chat":{"type":"private","id":1001}}}})
    assert bot.alerts[-1][2] is True


@pytest.mark.asyncio
async def test_edit_business_media_uses_supported_multipart_field():
    received={}
    async def media(request):
        assert request.path.endswith('/editMessageMedia')
        async for part in await request.multipart():
            received[part.name]=await part.read() if part.name=='gift' else await part.text()
        return web.json_response({"ok":True,"result":{"message_id":77,"photo":[{"file_id":"ok"}]}})
    app=web.Application()
    app.router.add_post('/botFAKE/editMessageMedia',media)
    async with TestServer(app) as server:
        tg=Telegram('fake')
        await tg.start()
        tg._base=str(server.make_url('/botFAKE/'))
        try:
            answer=await tg.edit_business_offer(999,77,'biz','text',b'JPEGDATA',None,
                                                'DEMO caption',kb.test_offer_keyboard())
        finally:
            await tg.close()
    assert answer['message_id']==77
    assert received['gift']==b'JPEGDATA'
    assert json.loads(received['media'])['media']=='attach://gift'
    assert received['business_connection_id']=='biz'
    assert json.loads(received['reply_markup'])['inline_keyboard']


@pytest.mark.asyncio
async def test_business_delete_api_shape():
    received={}
    async def delete_business(request):
        received.update(await request.json())
        return web.json_response({"ok":True,"result":True})
    app=web.Application()
    app.router.add_post('/botFAKE/deleteBusinessMessages',delete_business)
    async with TestServer(app) as server:
        tg=Telegram('fake')
        await tg.start()
        tg._base=str(server.make_url('/botFAKE/'))
        try:
            await tg.delete_business_source('biz',123)
        finally:
            await tg.close()
    assert received == {'business_connection_id':'biz','message_ids':'[123]'}


@pytest.mark.asyncio
async def test_caption_edit_preserves_user_supplied_photo(v4_store,config,monkeypatch):
    bot=EditingTelegram()
    msg=await setup_business(v4_store,bot)
    msg["text"]=None
    msg["caption"]="https://t.me/nft/InputKey-25057 500 15"
    msg["photo"]=[{"file_id":"photo-from-owner"}]
    async def no_network(_):
        pytest.fail("must reuse owner's NFT photo, not fetch image")
    monkeypatch.setattr("app.handlers.fetch_gift_image",no_network)
    await AppHandler(config,v4_store,bot).dispatch({"update_id":20001,"business_message":msg})
    assert [operation[0] for operation in bot.operations]==["edit"]
    assert bot.operations[0][4]=="photo"
    assert bot.operations[0][5] is None
    assert v4_store.offers_by_creator(1001)[1][0].telegram_message_id==11


@pytest.mark.asyncio
async def test_no_business_offer_until_customer_writes(v4_store,config,monkeypatch):
    bot=EditingTelegram()
    v4_store.connection_update(bot.remote)
    now=int(datetime.now(timezone.utc).timestamp())
    msg={"business_connection_id":"biz-v4","message_id":11,"date":now,
         "from":{"id":1001},"chat":{"type":"private","id":2002},
         "text":"https://t.me/nft/InputKey-25057 1000 15"}
    await AppHandler(config,v4_store,bot).dispatch({"update_id":20002,"business_message":msg})
    assert bot.operations==[]
    assert not v4_store.offers_by_creator(1001)[1]


@pytest.mark.asyncio
async def test_diagnostics_reports_webhook_status(v4_store,config):
    class DiagTelegram(InlineTelegram):
        def __init__(self):
            super().__init__()
            self.messages=[]
        async def api(self,method,**kwargs):
            if method == "getMe":
                return {"username": "demo_bot", "supports_guest_queries": False, "supports_inline_queries": True}
            assert method=="getWebhookInfo"
            return {"url":config.webhook_endpoint,"pending_update_count":0,"last_error_message":""}
        async def send_message(self, chat_id, text, markup=None, business_id=None):
            self.messages.append((chat_id,text))
            return {"message_id":55}
    bot=DiagTelegram()
    h=AppHandler(config,v4_store,bot)
    await h.dispatch({"update_id":20003,"message":{
        "chat":{"id":1001,"type":"private"},"from":{"id":1001},"text":"/diag"}})
    assert len(bot.messages)==1
    assert "совпадает" in bot.messages[0][1]
    assert "Бот от A/X T’eams" in bot.messages[0][1]
    await h.dispatch({"update_id":20004,"message":{
        "chat":{"id":2002,"type":"private"},"from":{"id":2002},"text":"/diag"}})
    assert "Нет доступа" in bot.messages[-1][1]


@pytest.mark.asyncio
async def test_inline_api_serializes_results_json():
    received={}
    async def answer_inline(request):
        received.update(await request.json())
        return web.json_response({"ok":True,"result":True})
    app=web.Application()
    app.router.add_post('/botFAKE/answerInlineQuery',answer_inline)
    async with TestServer(app) as server:
        tg=Telegram('fake')
        await tg.start()
        tg._base=str(server.make_url('/botFAKE/'))
        try:
            await tg.answer_inline('example-id',[{"type":"article","id":"a", "title":"demo",
                "input_message_content":{"message_text":"DEMO"}}])
        finally:
            await tg.close()
    assert received['is_personal'] is True
    assert received['cache_time']==0
    assert json.loads(received['results'])[0]['type']=='article'


def test_test_offer_keyboard_and_footer():
    assert "🧪" in rnd.test_offer_caption()
    assert "30 минут" in rnd.test_offer_caption()
    assert "Бот от A/X" not in rnd.test_offer_caption()
    assert "test:accept" in json.dumps(kb.test_offer_keyboard())
    assert "test:transfer" not in json.dumps(kb.test_offer_keyboard('accepted'))
    assert "test:instructions" in json.dumps(kb.test_offer_keyboard('accepted'))
