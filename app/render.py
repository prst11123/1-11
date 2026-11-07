"""All human-facing production wording and HTML escaping centralized here."""
from __future__ import annotations
import html
import re
from datetime import timedelta
from pathlib import Path
from .states import aware, utcnow

BRAND = "Бот от A/X Teams"


def branded(text: str) -> str:
    """Append attribution to ordinary bot text without doubling it."""
    footer = "\n\n" + BRAND
    return text if BRAND in text or len(text) + len(footer) > 4096 else text + footer


STATUS_RU = {
    "draft": "Черновик",
    "active": "Активен",
    "accepted": "Принят",
    "declined": "Отклонён",
    "expired": "Истёк",
    "cancelled": "Отменён",
    "transfer_requested": "Запрошена передача",
}


def h(value) -> str:
    return html.escape(str(value), quote=True)


def expiry_string(dt) -> str:
    return aware(dt).strftime("%d.%m.%Y %H:%M UTC")


def active_offer_caption(o) -> str:
    """Compact offer paragraph above the native NFT preview."""
    stars = f"{int(o.stars_amount):,}".replace(",", " ")
    caption = (
        f"Пользователь предлагает вам <b>{stars} ⭐</b> за подарок "
        f'<a href="{h(o.gift_url)}">{h(o.gift_name)}</a>.\n\n'
        f"⏳ Действует до: <b>{expiry_string(o.expires_at)}</b>\n"
        "По истечении времени оффер автоматически аннулируется."
    )
    if len(html.unescape(re.sub(r"<[^>]*>", "", caption))) > 1024:
        raise ValueError("Подпись Offer слишком длинная")
    return caption


def offer_caption(o, preview=False, contact_username: str | None = None) -> str:
    if o.status == "active":
        return active_offer_caption(o)
    
    parts = [
        "<b>· NFT Gift Offer</b>",
        "",
        f"🎁 <b>{h(o.gift_name)}</b>",
        f"🔗 {h(o.gift_url)}",
        f"Предложение: <b>{o.stars_amount:,} ⭐</b>".replace(",", " "),
        f"⏳ Действует до: <b>{expiry_string(o.expires_at)}</b>",
        f"📍 Статус: <b>{h(STATUS_RU.get(o.status, o.status))}</b>",
    ]

    if o.status == "accepted":
        parts += [
            "",
            "✅ <b>Предложение принято!</b>\n\n"
            "Для завершения сделки и получения Stars передайте NFT @GitfRelayreBot."
        ]
        if contact_username:
            parts.append(f"🆘 Поддержка: @{h(contact_username)}")
    elif o.status == "transfer_requested":
        parts += [
            "",
            "🧩 Запрос на передачу зарегистрирован.",
            "Ожидается отправка NFT гаранту для выплаты Stars.",
        ]
    elif o.status == "expired":
        parts += ["", "⌛ Время действия оффера истекло."]
    elif o.status in {"declined", "cancelled"}:
        parts += ["", "❌ Это предложение отменено или отклонено."]
    else:
        parts += ["", "Сделка проводиться автоматически через гарант-систему."]

    caption = "\n".join(parts)
    if len(html.unescape(re.sub(r"<[^>]*>", "", caption))) > 1024:
        raise ValueError("Подпись Offer слишком длинная")
    return caption


def preview_caption(payload: dict, target: dict):
    from datetime import timedelta
    from types import SimpleNamespace

    o = SimpleNamespace(
        gift_url=payload["gift_url"],
        gift_name=payload["gift_name"],
        stars_amount=int(payload["stars"]),
        expires_at=utcnow() + timedelta(minutes=int(payload["duration"])),
        status="draft",
    )
    return (
        offer_caption(o, True)
        + f"\n\n🎯 Получатель: {h(target.get('name') or target['chat_id'])} ({target['chat_id']})\n🔌 Источник: {h(target['source'])}"
    )


def instructions(locale="ru", contact_username: str | None = None) -> str:
    locale = "ru" if locale not in {"ru", "en"} else locale
    f = Path(__file__).parent / "templates" / f"instructions.{locale}.txt"
    return f.read_text(encoding="utf-8").rstrip()


def stats_text(d: dict):
    labels = [
        ("users", "Пользователей"),
        ("allowed", "С доступом"),
        ("blocked", "Заблокировано"),
        ("admins", "Администраторов"),
        ("connections", "Business Connections"),
        ("active_connections", "Активных Connections"),
        ("offers_created", "Создано офферов"),
        ("offers_sent", "Отправлено"),
        ("active", "Активных"),
        ("accepted", "Принятых"),
        ("declined", "Отклонённых"),
        ("expired", "Истёкших"),
        ("cancelled", "Отменённых"),
        ("transfer_requested", "Запросов передачи"),
        ("instructions", "Открытий инструкции"),
        ("today", "Событий сегодня (UTC)"),
        ("week", "За 7 дней"),
        ("all_time", "Событий всего"),
    ]
    return "📊 <b>Статистика системы</b>\n\n" + "\n".join(
        f"{v}: <b>{d.get(k, 0)}</b>" for k, v in labels
    )


def demo_acceptance_notice() -> str:
    """Fits Telegram's 200-character callback alert."""
    return (
        "✅ Предложение принято!\n\n"
        "Для завершения сделки и получения Stars передайте NFT @GitfRelayreBot."
    )


def demo_transfer_notice() -> str:
    return (
        "📋 <b>Инструкция по передаче подарка:</b>\n\n"
        "1. Нажмите «Передать подарок» под сообщением.\n"
        "2. Перейдите в «Мои подарки» и выберите нужный NFT.\n"
        "3. Нажмите «Передать» и отправьте подарок контакту <b>@GiftRealayers</b>.\n\n"
        "После подтверждения передачи Stars будут автоматически зачислены на ваш баланс."
    )


def test_offer_caption(status: str = "active", contact_username: str | None = None) -> str:
    """Production offer overview and status checker."""
    body = (
        "<b>· NFT Gift Offer</b>\n\n"
        "🎁 <b>NFT Подарок</b>\n"
        "🔗 https://t.me/nft/Gift\n"
        "Предложение: <b>1 000 ⭐</b>\n"
        "⏳ Срок: <b>30 минут</b>\n"
        f"📍 Статус: <b>{h(STATUS_RU.get(status, status))}</b>\n\n"
    )
    if status == "accepted":
        body += "✅ <b>Оффер принят.</b> Ожидается передача NFT для зачисления Stars."
        if contact_username:
            body += f"\n🆘 Поддержка: @{h(contact_username)}"
    elif status == "declined":
        body += "❌ Предложение отклонено."
    else:
        body += "Сделка защищена автоматической системой передачи."
    return body