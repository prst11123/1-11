"""Telegram Guest Mode: explicit, authorized DEMO cards in arbitrary eligible chats.

The guest bot is summoned by mentioning @bot_username. It posts a *separate*
message as the bot; it cannot edit the user's triggering message or hide origin.
"""
from __future__ import annotations

import re
import hashlib
import hmac
from html import escape

from .quick_offer import QuickOffer, parse_quick_offer
from .states import default_gift_name, validate_gift_url, aware

_MENTION = re.compile(r"^@([A-Za-z0-9_]{5,32})(?:\s+|$)")


def parse_guest_invocation(text: str, bot_username: str,
                           default_url: str, default_stars: int,
                           default_duration: int) -> QuickOffer | None:
    """Only explicit, addressed mentions may create guest messages."""
    match = _MENTION.match(text.strip())
    if not match or match.group(1).casefold() != bot_username.lstrip('@').casefold():
        return None
    args = text.strip()[match.end():].strip()
    if args.casefold() in {'#тестофер', '/testoffer', 'тестофер'}:
        url = validate_gift_url(default_url)
        return QuickOffer(url, default_gift_name(url), default_stars, default_duration)
    return parse_quick_offer(args)


def guest_callback_token(secret: str, offer_id: int, query_id: str) -> str:
    """Authenticate Guest buttons even after an ambiguous delivery timeout."""
    payload = f"guest:{offer_id}:{query_id}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()[:24]


def guest_caption(offer, status: str = "active", contact_username: str | None = None) -> str:
    """Clearly labelled demonstration, never a completed sale or payout."""
    heading = (f"🧪 <b>DEMO-офер</b>\n\n"
               f'🎁 <a href="{escape(offer.gift_url, quote=True)}"><b>{escape(offer.gift_name)}</b></a>\n'
               f"⭐ Предложение: <b>{int(offer.stars_amount):,} Stars (DEMO)</b>\n".replace(',', ' ')
               )
    if status == 'active':
        return heading + (f"⏳ Срок до: <b>{aware(offer.expires_at).strftime('%d.%m.%Y %H:%M UTC')}</b>\n\n"
                          "Тестовый офер. NFT и Stars не переводятся.")
    if status == 'accepted':
        contact = f"\n🆘 Поддержка: @{escape(contact_username)}" if contact_username else ""
        return heading + "\n✅ <b>Принято (DEMO)</b>\nNFT не продан, Stars не начислены. Ничего не переводите." + contact
    if status == 'declined':
        return heading + "\n❌ <b>Отклонено (DEMO)</b>\nОплаты и передачи NFT не было."
    if status == 'expired':
        return heading + "\n⌛ <b>Срок истёк (DEMO)</b>\nОплаты и передачи NFT не было."
    return heading + "\n🧪 <b>Тест завершён</b>"


def guest_keyboard(offer_id: int, status: str = "active", token: str | None = None,
                   contact_username: str | None = None) -> dict:
    if status == "accepted":
        suffix = f"{token}:{offer_id}" if token else str(offer_id)
        rows = [[{"text": "ℹ️ Что означает DEMO?", "callback_data": f"guest:instructions:{suffix}"}]]
        if contact_username:
            rows.append([{"text": "🆘 Поддержка", "url": f"https://t.me/{contact_username}"}])
        return {"inline_keyboard": rows}
    if status != "active":
        return {"inline_keyboard": []}
    suffix = f"{token}:{offer_id}" if token else str(offer_id)
    return {"inline_keyboard": [[
        {"text": "✕ Отклонить", "callback_data": f"guest:decline:{suffix}"},
        {"text": "✓ Принять", "callback_data": f"guest:accept:{suffix}"},
    ]]}


def guest_result(offer, with_preview: bool = True, token: str | None = None) -> dict:
    """A text message with native Telegram NFT-link preview and exactly two buttons."""
    message = {"message_text": guest_caption(offer), "parse_mode": "HTML"}
    message["link_preview_options"] = (
        {"url": offer.gift_url, "prefer_large_media": True}
        if with_preview else {"is_disabled": True}
    )
    return {
        "type": "article", "id": f"guest-{offer.id}",
        "title": f"🧪 DEMO {offer.gift_name}"[:100],
        "input_message_content": message,
        "reply_markup": guest_keyboard(offer.id, token=token),
    }
