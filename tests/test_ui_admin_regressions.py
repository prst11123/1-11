"""Regression coverage for offer controls and persistent private admin flows."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import keyboards as kb
from app import render as rnd
from app.db import Database
from app.handlers import AppHandler
from app.models import Base
from app.states import utcnow
from app.store import Store


@pytest.fixture
def ui_store(config, tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "ui.db"))
    Base.metadata.create_all(db.engine)
    store = Store(db, config)
    store.initialize_admins()
    yield store
    db.close()


class Bot:
    def __init__(self):
        self.messages = []
        self.media = []
        self.callbacks = []
        self.edits = []

    async def send_message(self, chat_id, text, markup=None, business_id=None):
        self.messages.append((chat_id, text, markup))
        return {"message_id": 12}

    async def send_media(self, *args, **kwargs):
        self.media.append((args, kwargs))
        return {"message_id": 11}

    async def answer_callback(self, cid, text="", alert=False):
        self.callbacks.append((cid, text, alert))

    async def edit_test_caption(self, *args):
        self.edits.append(args)


def message(text, uid=1002):
    return {"chat": {"id": uid, "type": "private"}, "from": {"id": uid}, "text": text}


def callback(data, cid="callback", uid=1002):
    return {"id": cid, "data": data, "from": {"id": uid},
            "message": {"message_id": 11, "chat": {"id": uid, "type": "private"}}}


def test_public_and_private_active_cards_have_two_decision_buttons():
    offer = SimpleNamespace(id=123, status="active", gift_url="https://t.me/nft/InputKey-25057")
    for keyboard in (kb.offer_keyboard(offer), kb.test_offer_keyboard(),
                     kb.inline_offer_keyboard(123, offer.gift_url, "active", "p")):
        assert [b["text"] for row in keyboard["inline_keyboard"] for b in row] == [
            "✕ Отклонить", "✓ Принять"]


def test_escaped_gift_name_is_checked_after_html_entity_parsing():
    offer = SimpleNamespace(gift_name="&" * 150, gift_url="https://t.me/nft/InputKey-25057",
                            stars_amount=1000, status="accepted", expires_at=utcnow()+timedelta(minutes=30))
    caption = rnd.offer_caption(offer, contact_username="support_team")
    assert "&amp;" * 150 in caption
    assert "NFT не передан" in caption


@pytest.mark.asyncio
async def test_faq_is_available_to_a_user_without_creation_access(config, ui_store):
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    ui_store.set_display_contact(1002, "support_team")
    await handler.on_message(message("/faq@DemoNFTBot", uid=8080))
    assert "FAQ" in bot.messages[-1][1]
    assert "@support_team" in bot.messages[-1][1]
    assert not ui_store.can_create(8080)


@pytest.mark.asyncio
async def test_test_button_cancels_pending_faq_input_and_keeps_share(config, ui_store):
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    await handler.on_callback(callback("admin:faqedit"))
    initial = ui_store.display_faq()
    await handler.on_message(message("🧪 Тест офера"))
    assert ui_store.flow(1002)[0] is None
    assert ui_store.display_faq() == initial
    assert len(bot.media) == 1
    assert bot.messages[-1][2] == kb.test_share_keyboard()
    await handler.on_message(message("An unrelated later message must not replace the FAQ."))
    assert ui_store.display_faq() == initial


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["admin:panel", "admin:home", "admin:faqreset", "admin:contactreset"])
async def test_admin_navigation_exits_pending_input(config, ui_store, data):
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    await handler.on_callback(callback("admin:contactedit", cid="edit-contact"))
    assert ui_store.flow(1002)[0] == "ADMIN_CONTACT_INPUT"
    await handler.on_callback(callback(data, cid="navigate"))
    assert ui_store.flow(1002)[0] is None


@pytest.mark.asyncio
async def test_support_contact_full_flow_validation_and_persistence(config, ui_store):
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    await handler.on_callback(callback("admin:contactedit"))
    await handler.on_message(message("https://t.me/unsafe?query=1"))
    assert ui_store.flow(1002)[0] == "ADMIN_CONTACT_INPUT"
    assert ui_store.display_contact()[0] is None
    await handler.on_message(message("@Support_Team"))
    assert ui_store.flow(1002)[0] is None
    assert Store(ui_store.db, config).display_contact() == ("support_team", "Админ-панель")
    await handler.on_message(message("❓ FAQ"))
    assert "@support_team" in bot.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_command_exits_pending_contact_input(config, ui_store):
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    await handler.on_callback(callback("admin:contactedit"))
    await handler.on_message(message("/admin@DemoNFTBot"))
    assert ui_store.flow(1002)[0] is None
    assert "Админ-панель" in bot.messages[-1][1]


@pytest.mark.asyncio
async def test_blocked_user_cannot_press_an_old_test_button(config, ui_store):
    ui_store.set_user_access(1001, 8080, "allow")
    ui_store.set_user_access(1001, 8080, "block")
    bot = Bot()
    handler = AppHandler(config, ui_store, bot)
    await handler.on_callback(callback("test:accept", uid=8080))
    assert not bot.edits
    assert "Нет доступа" in bot.callbacks[-1][1]
    assert bot.callbacks[-1][2]


@pytest.mark.asyncio
async def test_custom_faq_is_plain_text_without_html_injection(config, ui_store):
    faq = "<b>Untrusted markup</b> & contact information for the demo."
    ui_store.set_faq_text(1002, faq)
    bot = Bot()
    await AppHandler(config, ui_store, bot).on_message(message("❓ FAQ"))
    assert "&lt;b&gt;Untrusted markup&lt;/b&gt; &amp;" in bot.messages[-1][1]
