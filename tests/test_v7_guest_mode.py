"""Tests for Telegram 10.0 Guest Mode: no inline picker, no Business prerequisite."""
from types import SimpleNamespace

import pytest

from app.handlers import AppHandler
from app.guest_offers import parse_guest_invocation, guest_keyboard, guest_caption, guest_result
from app.telegram import Telegram
from app.db import Database
from app.models import Base
from app.store import Store
from app.states import utcnow
from datetime import timedelta


@pytest.fixture
def guest_store(config, tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "guest_test.db"))
    Base.metadata.create_all(db.engine)
    store = Store(db, config)
    store.initialize_admins()
    yield store
    db.close()


class GuestTelegram:
    def __init__(self):
        self.sent=[]
        self.edited=[]
        self.callbacks=[]
    async def answer_guest(self,query_id,result):
        self.sent.append((query_id,result))
        return {"inline_message_id":"guestMsg1"}
    async def edit_guest_offer(self,message_id,text,markup,gift_url):
        self.edited.append((message_id,text,markup,gift_url))
    async def answer_callback(self,cid,text="",alert=False):
        self.callbacks.append((cid,text,alert))


def test_explicit_command_only():
    link="https://t.me/nft/InputKey-25057"
    c=parse_guest_invocation("@qwe333qwe_bot\n" + link + "\n1900\n15", "qwe333qwe_bot",link,1000,30)
    assert (c.stars,c.duration,c.gift_name)==(1900,15,"InputKey #25057")
    assert parse_guest_invocation("hello " + link + " 1900 15", "qwe333qwe_bot",link,1000,30) is None
    assert parse_guest_invocation("@different_bot " + link + " 1900 15", "qwe333qwe_bot",link,1000,30) is None
    assert parse_guest_invocation("@qwe333qwe_bot", "qwe333qwe_bot",link,1000,30) is None
    assert parse_guest_invocation("@qwe333qwe_bot #тестофер", "qwe333qwe_bot",link,1000,30).duration==30


@pytest.mark.asyncio
async def test_authorized_guest_post_is_exactly_one_demo_card(guest_store, config):
    tg=GuestTelegram()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    msg={"guest_query_id":"GUEST-01", "from":{"id":1001}, "chat":{"id":2002, "type":"private"},
         "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}
    await h.dispatch({"update_id":970001,"guest_message":msg})
    assert len(tg.sent)==1
    query, result=tg.sent[0]
    assert query=="GUEST-01"
    assert result["type"]=="article"
    assert result["reply_markup"]=={"inline_keyboard":[[
        {"text":"✕ Отклонить", "callback_data":result["reply_markup"]["inline_keyboard"][0][0]["callback_data"]},
        {"text":"✓ Принять", "callback_data":result["reply_markup"]["inline_keyboard"][0][1]["callback_data"]}
    ]]}
    assert len(result["reply_markup"]["inline_keyboard"][0])==2
    assert result["input_message_content"]["link_preview_options"]["url"]=="https://t.me/nft/InputKey-25057"
    assert "DEMO" in result["input_message_content"]["message_text"]
    assert "продан" not in result["input_message_content"]["message_text"].lower()
    await h.dispatch({"update_id":970001,"guest_message":msg})
    assert len(tg.sent)==1


@pytest.mark.asyncio
async def test_guest_accept_from_user_who_has_never_started_bot(guest_store, config):
    tg=GuestTelegram()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970002,"guest_message":{
        "guest_query_id":"GUEST-02", "from":{"id":1001},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    offer_id=int(tg.sent[0][1]["reply_markup"]["inline_keyboard"][0][1]["callback_data"].split(':')[-1])
    await h.dispatch({"update_id":970003,"callback_query":{
        "id":"CB-GUEST-1", "from":{"id":2002, "first_name":"Recipient"},
        "inline_message_id":"guestMsg1", "data":f"guest:accept:{offer_id}"}})
    assert len(tg.edited)==1
    inline_id,text,markup,gift_url=tg.edited[0]
    assert inline_id=="guestMsg1" and gift_url=="https://t.me/nft/InputKey-25057"
    assert "Принято (DEMO)" in text and "не начислены" in text
    assert markup["inline_keyboard"][0][0]["text"] == "Как передать?"
    assert tg.callbacks[-1][2] is True
    assert "NFT не передан" in tg.callbacks[-1][1]
    assert len(tg.callbacks)==1


@pytest.mark.asyncio
async def test_guest_decline_updates_message(guest_store, config):
    tg=GuestTelegram()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970004,"guest_message":{
        "guest_query_id":"GUEST-03", "from":{"id":1001},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    offer_id=int(tg.sent[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(':')[-1])
    await h.dispatch({"update_id":970005,"callback_query":{
        "id":"CB-GUEST-2", "from":{"id":2002},
        "inline_message_id":"guestMsg1", "data":f"guest:decline:{offer_id}"}})
    assert "Отклонено (DEMO)" in tg.edited[0][1]


@pytest.mark.asyncio
async def test_guest_unapproved_sender_ignored(guest_store, config):
    tg=GuestTelegram()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970006,"guest_message":{
        "guest_query_id":"GUEST-04", "from":{"id":3333},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    assert tg.sent==[]


@pytest.mark.asyncio
async def test_guest_not_received_without_mention_match(guest_store, config):
    tg=GuestTelegram()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970007,"guest_message":{
        "guest_query_id":"GUEST-05", "from":{"id":1001},
        "text":"@other_bot https://t.me/nft/InputKey-25057 1900 15"}})
    assert tg.sent==[]


def test_transport_subscribes_to_guest_message():
    import inspect
    src=inspect.getsource(Telegram.set_webhook)
    assert '"guest_message"' in src

@pytest.mark.asyncio
async def test_guest_preview_rejection_falls_back_to_text_card(guest_store, config):
    from app.telegram import TelegramError
    class PreviewFailure(GuestTelegram):
        async def answer_guest(self, query_id, result):
            self.sent.append((query_id, result))
            if len(self.sent)==1:
                raise TelegramError("answerGuestQuery",400,"Preview not available")
            return {"inline_message_id":"msg-fallback"}
    tg=PreviewFailure()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970008,"guest_message":{
        "guest_query_id":"GUEST-08", "from":{"id":1001},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    assert len(tg.sent)==2
    assert tg.sent[-1][1]["input_message_content"]["link_preview_options"]=={"is_disabled":True}
    assert len(tg.sent[-1][1]["reply_markup"]["inline_keyboard"][0])==2


@pytest.mark.asyncio
async def test_guest_timeout_does_not_duplicate_post(guest_store, config):
    from app.telegram import TelegramError
    class Timeout(GuestTelegram):
        async def answer_guest(self, query_id, result):
            self.sent.append((query_id, result))
            raise TelegramError("answerGuestQuery",0,"Network timeout")
    tg=Timeout()
    h=AppHandler(config,guest_store,tg)
    h.bot_username="qwe333qwe_bot"
    await h.dispatch({"update_id":970009,"guest_message":{
        "guest_query_id":"GUEST-09", "from":{"id":1001},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    await h.dispatch({"update_id":970009,"guest_message":{
        "guest_query_id":"GUEST-09", "from":{"id":1001},
        "text":"@qwe333qwe_bot https://t.me/nft/InputKey-25057 1900 15"}})
    assert len(tg.sent)==1
