"""Acceptance screen is a clearly labeled demo and uses editable support contact."""
from datetime import timedelta
from types import SimpleNamespace
import json

import pytest

from app.handlers import AppHandler
from app.db import Database
from app.models import Base
from app.store import Store
from app import keyboards as kb
from app import render as rnd
from app.states import utcnow


@pytest.fixture
def v6_store(config, tmp_path):
    db=Database("sqlite:///"+str(tmp_path / "v6.db"))
    Base.metadata.create_all(db.engine)
    store=Store(db,config)
    store.initialize_admins()
    yield store
    db.close()


class SpyTelegram:
    def __init__(self):
        self.edits = []
        self.callbacks = []
        self.answers = []

    async def edit_test_caption(self, chat_id, message_id, caption, markup):
        self.edits.append((chat_id, message_id, caption, markup))
        return True

    async def edit_inline_offer(self, inline_id, caption, markup, photo):
        self.edits.append((inline_id, caption, markup, photo))
        return True

    async def answer_callback(self, callback_id, text="", alert=False):
        self.callbacks.append((callback_id, text, alert))
        return True

    async def answer_inline(self, query_id, results):
        self.answers.append(results)
        return True


def test_second_stage_keyboard_is_not_transfer_request():
    offer = SimpleNamespace(id=12, status="accepted", gift_url="https://t.me/nft/InputKey-25057")
    for markup in [kb.offer_keyboard(offer,"help_team"),
                   kb.test_offer_keyboard("accepted","help_team"),
                   kb.inline_offer_keyboard(12,offer.gift_url,"accepted","p","help_team")]:
        buttons = [button for row in markup["inline_keyboard"] for button in row]
        labels = " ".join(b["text"] for b in buttons)
        assert "Передать" not in labels
        assert any(b["text"] == "Как передать?" for b in buttons)
        assert any(b.get("url") == "https://t.me/help_team" for b in buttons)
        assert not any("transfer" in b.get("callback_data","") for b in buttons)


def test_caption_does_not_claim_sale_or_payout():
    offer = SimpleNamespace(gift_name="Input Key #25057", gift_url="https://t.me/nft/InputKey-25057",
                            stars_amount=1000,expires_at=utcnow()+timedelta(minutes=30),status="accepted")
    text = rnd.offer_caption(offer,contact_username="help_team")
    assert "@help_team" in text
    assert "продажи" in text.lower()
    assert "не начислены" in text
    assert "не отправляйте" in text.lower()
    assert "Подарок успешно продан" not in text
    assert "Бот от A/X" not in text
    assert len(text) <= 1024


@pytest.mark.asyncio
async def test_private_test_accept_uses_latest_admin_contact(config,v6_store):
    v6_store.set_display_contact(1001,"first_help")
    v6_store.set_display_contact(1001,"second_help")
    bot = SpyTelegram()
    handler = AppHandler(config,v6_store,bot)
    await handler.dispatch({"update_id":99201,"callback_query":{
        "id":"accept-demo-1","from":{"id":1001},"data":"test:accept",
        "message":{"message_id":44,"chat":{"id":1001,"type":"private"}}}})
    assert len(bot.edits) == 1
    _, _, caption, markup = bot.edits[0]
    assert "@second_help" in caption and "first_help" not in caption
    assert "https://t.me/second_help" in json.dumps(markup)
    assert "Подарок не продан" in caption


@pytest.mark.asyncio
async def test_old_private_transfer_button_is_safe_and_readonly(config,v6_store):
    bot=SpyTelegram()
    handler=AppHandler(config,v6_store,bot)
    await handler.dispatch({"update_id":99202,"callback_query":{
        "id":"old-transfer","from":{"id":1001},"data":"test:transfer",
        "message":{"message_id":44,"chat":{"id":1001,"type":"private"}}}})
    assert not bot.edits
    assert len(bot.callbacks)==1 and bot.callbacks[0][2] is True
    assert "не нужно" in bot.callbacks[0][1]
    assert "Это демо-бот" in bot.callbacks[0][1]


@pytest.mark.asyncio
async def test_inline_accepted_contact_is_new_admin_value(config,v6_store):
    bot=SpyTelegram()
    handler=AppHandler(config,v6_store,bot)
    await handler.dispatch({"update_id":99203,"inline_query":{
        "id":"q100","from":{"id":1001},"query":"https://t.me/nft/InputKey-25057 1000 30"}})
    offer_id=int(bot.answers[-1][0]["id"][1:-1])
    v6_store.set_display_contact(1001,"faq_team")
    await handler.dispatch({"update_id":99204,"callback_query":{
        "id":"inline-accept-1","from":{"id":2002},"data":f"inline:accept:{offer_id}:t",
        "inline_message_id":"inline-message-100"}})
    assert len(bot.edits)==1
    _, caption, markup, photo=bot.edits[-1]
    assert photo is False
    assert "@faq_team" in caption
    assert any(b.get("url")=="https://t.me/faq_team" for r in markup["inline_keyboard"] for b in r)
    assert "не начислены" in caption
