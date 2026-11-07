"""Guest delivery, authentic message binding and recipient-only DEMO actions."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import Database
from app.handlers import AppHandler
from app.models import Base, InlineOffer, InlineMessageState
from app.states import utcnow
from app.store import Store, DomainError
from app.telegram import TelegramError


@pytest.fixture
def guest_app(config, tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "guest-regressions.db"))
    Base.metadata.create_all(db.engine)
    store = Store(db, config)
    store.initialize_admins()
    bot = GuestBot()
    handler = AppHandler(config, store, bot)
    handler.bot_username = "demo_gift_bot"
    yield handler, store, bot
    db.close()


class GuestBot:
    def __init__(self):
        self.answers = []
        self.edits = []
        self.callbacks = []
        self.fail_delivery = False
        self.fail_edit = False

    async def answer_guest(self, query_id, result):
        self.answers.append((query_id, result))
        if self.fail_delivery:
            raise TelegramError("answerGuestQuery", 0, "Network timeout")
        return {"inline_message_id": "original-guest-message"}

    async def answer_inline(self, query_id, results):
        self.answers.append((query_id, results))

    async def edit_guest_offer(self, message_id, text, markup, gift_url):
        self.edits.append((message_id, text, markup, gift_url))
        if self.fail_edit:
            raise TelegramError("editMessageText", 0, "Network timeout")

    async def edit_inline_offer(self, message_id, text, markup, photo):
        self.edits.append((message_id, text, markup, photo))

    async def answer_callback(self, cid, text="", alert=False):
        self.callbacks.append((cid, text, alert))


def invocation(query_id="guest-query", **extra):
    return {"guest_query_id": query_id, "from": {"id": 1001},
            "chat": {"id": 2002, "type": "private"},
            "text": "@demo_gift_bot https://t.me/nft/InputKey-25057 1900 15", **extra}


def button(bot, index=1):
    return bot.answers[0][1]["reply_markup"]["inline_keyboard"][0][index]["callback_data"]


async def click(handler, data, message_id="original-guest-message", user_id=2002, cid="click"):
    await handler.on_callback({"id": cid, "from": {"id": user_id},
                               "data": data, "inline_message_id": message_id})


@pytest.mark.asyncio
async def test_guest_query_deduplicates_even_with_different_update_id(guest_app):
    handler, store, bot = guest_app
    await handler.dispatch({"update_id": 1, "guest_message": invocation()})
    await handler.dispatch({"update_id": 2, "guest_message": invocation()})
    assert len(bot.answers) == 1
    with store.db.transaction() as session:
        offers = session.scalars(select(InlineOffer)).all()
        assert len(offers) == 1
        assert offers[0].guest_inline_message_id == "original-guest-message"


@pytest.mark.asyncio
async def test_guest_callback_is_bound_to_returned_message(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    offer_id = button(bot).split(":")[-1]
    await click(handler, f"guest:accept:{offer_id}", "other-message")
    assert bot.edits == []
    assert bot.callbacks[-1][2] is True
    await click(handler, button(bot), "participant-alias", cid="signed-message")
    assert "Принято (DEMO)" in bot.edits[-1][1]
    assert bot.edits[-1][0] == "original-guest-message"
    with store.db.transaction() as session:
        states = session.scalars(select(InlineMessageState)).all()
        assert len(states) == 1 and states[0].inline_message_id == "original-guest-message"


@pytest.mark.asyncio
async def test_guest_aliases_share_one_status_and_demo_modal(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    await click(handler, button(bot), "recipient-alias", cid="accept")
    assert bot.callbacks[-1][2] is True
    assert "Это DEMO" in bot.callbacks[-1][1]
    assert "NFT не передан" in bot.callbacks[-1][1]
    assert "Ничего переводить не нужно" in bot.callbacks[-1][1]
    assert len(bot.callbacks[-1][1]) <= 195
    info = bot.edits[-1][2]["inline_keyboard"][0][0]["callback_data"]
    assert info.startswith("guest:instructions:") and len(info.encode()) <= 64
    await click(handler, info, "another-participant-alias", cid="info")
    assert len(bot.edits) == 1  # information does not modify the offer
    assert bot.callbacks[-1][2] is True
    await click(handler, button(bot, 0), "recipient-alias", cid="decline-after-accept")
    assert len(bot.edits) == 1
    with store.db.transaction() as session:
        states = session.scalars(select(InlineMessageState)).all()
        assert len(states) == 1 and states[0].status == "accepted"


@pytest.mark.asyncio
async def test_guest_timeout_never_reposts_but_signed_button_recovers(guest_app):
    handler, store, bot = guest_app
    bot.fail_delivery = True
    await handler.on_guest_message(invocation())
    await handler.on_guest_message(invocation())
    assert len(bot.answers) == 1
    await click(handler, button(bot))
    assert "Принято (DEMO)" in bot.edits[-1][1]
    with store.db.transaction() as session:
        offer = session.scalar(select(InlineOffer))
        assert offer.guest_inline_message_id == "original-guest-message"


@pytest.mark.asyncio
async def test_guest_retry_after_already_edited_still_opens_demo_modal(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    await click(handler, button(bot), cid="first")
    async def unchanged(*args):
        raise TelegramError("editMessageText", 400, "Bad Request: message is not modified")
    bot.edit_guest_offer = unchanged
    await click(handler, button(bot), "recipient-alias", cid="retry")
    assert bot.callbacks[-1][2] is True
    assert "Это DEMO" in bot.callbacks[-1][1]


@pytest.mark.asyncio
async def test_unsigned_unconfirmed_guest_callback_cannot_claim_message(guest_app):
    handler, store, bot = guest_app
    bot.fail_delivery = True
    await handler.on_guest_message(invocation())
    offer_id = button(bot).split(":")[-1]
    await click(handler, f"guest:accept:{offer_id}")
    assert bot.edits == []
    assert bot.callbacks[-1][2] is True


@pytest.mark.asyncio
async def test_tampered_guest_button_is_rejected(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    parts = button(bot).split(":")
    parts[2] = "0" * 24
    await click(handler, ":".join(parts))
    assert bot.edits == []
    assert bot.callbacks[-1][2] is True
    assert len(button(bot).encode()) <= 64


@pytest.mark.asyncio
async def test_guest_offer_cannot_be_addressed_with_inline_callback(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    offer_id = button(bot).split(":")[-1]
    await click(handler, f"inline:accept:{offer_id}:t")
    assert bot.edits == []
    assert bot.callbacks[-1][2] is True


@pytest.mark.asyncio
async def test_guest_creator_cannot_accept_their_own_offer(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    await click(handler, button(bot), user_id=1001)
    assert bot.edits == []
    assert "/test" in bot.callbacks[-1][1]


@pytest.mark.asyncio
async def test_guest_accept_keeps_preview_and_uses_latest_support_contact(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    store.set_display_contact(1001, "new_support")
    assert store.user(2002) is None
    await click(handler, button(bot))
    _, text, markup, url = bot.edits[-1]
    assert "@new_support" in text and "не начислены" in text
    assert url == "https://t.me/nft/InputKey-25057"
    assert markup["inline_keyboard"][1][0]["url"] == "https://t.me/new_support"


@pytest.mark.asyncio
async def test_expired_guest_can_retry_display_after_failed_edit(guest_app):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation())
    with store.db.transaction() as session:
        session.scalar(select(InlineOffer)).expires_at = utcnow() - timedelta(seconds=1)
    bot.fail_edit = True
    await click(handler, button(bot))
    bot.fail_edit = False
    await click(handler, button(bot), cid="retry-expired")
    assert len(bot.edits) == 2
    assert "Срок истёк" in bot.edits[-1][1]
    assert bot.edits[-1][2] == {"inline_keyboard": []}
    with store.db.transaction() as session:
        assert session.scalar(select(InlineMessageState)).status == "expired"


@pytest.mark.asyncio
async def test_guest_caption_mention_is_supported(guest_app):
    handler, store, bot = guest_app
    msg = invocation()
    msg["caption"] = msg.pop("text")
    await handler.on_guest_message(msg)
    assert len(bot.answers) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"from": {"id": 1001, "is_bot": True}},
                                   {"sender_chat": {"id": -100123}}])
async def test_guest_bot_or_anonymous_chat_actor_is_ignored(guest_app, extra):
    handler, store, bot = guest_app
    await handler.on_guest_message(invocation(**extra))
    assert bot.answers == []


@pytest.mark.asyncio
async def test_inline_article_requests_exact_nft_preview(guest_app):
    handler, store, bot = guest_app
    await handler.on_inline_query({"id": "inline-query", "from": {"id": 1001},
                                   "query": "https://t.me/nft/InputKey-25057 1900 15"})
    result = bot.answers[-1][1][0]
    assert result["input_message_content"]["link_preview_options"] == {
        "url": "https://t.me/nft/InputKey-25057", "prefer_large_media": True}
    buttons = [b for row in result["reply_markup"]["inline_keyboard"] for b in row]
    assert [b["text"] for b in buttons] == ["✕ Отклонить", "✓ Принять"]


def test_legacy_inline_template_and_message_state_remain_usable(guest_app):
    handler, store, bot = guest_app
    offer = store.create_inline_offer(1001, {"gift_url": "https://t.me/nft/InputKey-25057",
                                           "gift_name": "InputKey #25057", "stars": 1900, "duration": 15})
    _, status = store.inline_action(offer.id, "legacy-inline-message", "accept", actor_id=2002)
    assert status == "accepted"
    with pytest.raises(DomainError):
        store.inline_action(offer.id, "legacy-inline-message", "decline", actor_id=2002)
