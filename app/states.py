"""Pure offer transition rules and user flow state names."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote
import re

WAIT_URL = "WAITING_GIFT_URL"
WAIT_STARS = "WAITING_STARS"
WAIT_EXPIRATION = "WAITING_EXPIRATION"
WAIT_IMAGE = "WAITING_IMAGE"
WAIT_NAME = "WAITING_NAME"
WAIT_TARGET = "WAITING_TARGET"
PREVIEW = "PREVIEW"
ADMIN_INPUT = "ADMIN_INPUT"

FINAL_STATUSES = frozenset({"declined", "expired", "cancelled", "transfer_requested"})
OFFER_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"accepted", "declined", "expired", "cancelled"},
    "accepted": {"transfer_requested"},
    "declined": set(),
    "expired": set(),
    "cancelled": set(),
    "transfer_requested": set(),
}
ACTION_TRANSITION = {"accept": "accepted", "decline": "declined", "transfer": "transfer_requested"}
ACTION_EVENT = {"accept": "OFFER_ACCEPTED", "decline": "OFFER_DECLINED", "transfer": "OFFER_TRANSFER_CLICKED"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_gift_url(text: str) -> str:
    text = text.strip()
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.hostname not in {"t.me", "www.t.me"} or parts.username or parts.password:
        raise ValueError("Нужна HTTPS-ссылка вида https://t.me/nft/...")
    if parts.port not in {None, 443} or not re.fullmatch(r"/nft/[A-Za-z0-9_-]{1,128}/?", parts.path) or parts.query or parts.fragment:
        raise ValueError("Неверная NFT-ссылка: https://t.me/nft/Название-123")
    return f"https://t.me{parts.path.rstrip('/')}"


def default_gift_name(url: str) -> str:
    return unquote(urlsplit(url).path.split("/")[-1]).replace("-", " ")[:100]


def parse_stars(text: str) -> int:
    if not re.fullmatch(r"[0-9]{1,13}", text.strip()):
        raise ValueError("Введите целое положительное количество Stars")
    value = int(text.strip())
    if not 1 <= value <= 10**12:
        raise ValueError("Stars: допустимый диапазон от 1 до 1 000 000 000 000")
    return value


def parse_duration(text: str) -> int:
    text = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,6})(m|м|мин|минут|h|ч|час)?", text)
    if not m:
        raise ValueError("Введите минуты, например 15, 30, 60 или 2ч")
    n = int(m.group(1)) * (60 if m.group(2) in {"h", "ч", "час"} else 1)
    if not 1 <= n <= 10080:
        raise ValueError("Допустим срок от 1 минуты до 7 дней")
    return n


def assert_transition(status: str, action: str, expires_at: datetime, now: datetime | None = None) -> str:
    if action not in ACTION_TRANSITION:
        raise ValueError("Неизвестное действие")
    now = now or utcnow()
    if status == "active" and aware(expires_at) <= now:
        raise ValueError("Срок действия предложения истёк")
    next_status = ACTION_TRANSITION[action]
    if next_status not in OFFER_TRANSITIONS.get(status, set()):
        raise ValueError(f"Действие недоступно для статуса {status}")
    return next_status
