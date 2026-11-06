"""Parse an authorized business owner's 3-field message into a DEMO offer.

Only messages matching the entire input grammar are commands. Ordinary chat
messages, including a lone NFT link, never create an offer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .states import default_gift_name, parse_duration, parse_stars, validate_gift_url

NFT_LINE = re.compile(r"^https://(?:www\.)?t\.me/nft/[A-Za-z0-9_-]{1,128}/?$", re.I)
DURATION = re.compile(r"^\d{1,6}\s*(?:m|м|мин|минут|h|ч|час)?$", re.I)
STARS = re.compile(r"^\d{1,13}$")


@dataclass(frozen=True)
class QuickOffer:
    gift_url: str
    gift_name: str
    stars: int
    duration: int


def parse_quick_offer(text: str) -> QuickOffer | None:
    """Accept exactly 3 lines or whitespace-separated fields, optional /offer prefix.

    Examples:
      https://t.me/nft/PlushPepe-123\n1000\n15м
      /offer https://t.me/nft/PlushPepe-123 1000 15
    """
    tokens = text.strip().split()
    if tokens and tokens[0].lower() in {"/offer", "офер", "/офер"}:
        tokens = tokens[1:]
    if len(tokens) != 3:
        return None
    url, stars, duration = tokens
    if not (NFT_LINE.fullmatch(url) and STARS.fullmatch(stars) and DURATION.fullmatch(duration)):
        return None
    gift_url = validate_gift_url(url)
    gift_name = default_gift_name(gift_url)
    # Readable NFT #serial, not an unverified title obtained from an unknown website.
    slug = gift_url.rsplit("/", 1)[-1]
    if "-" in slug and slug.rsplit("-", 1)[-1].isdigit():
        title, serial = slug.rsplit("-", 1)
        gift_name = f"{title} #{serial}"
    try:
        return QuickOffer(gift_url, gift_name[:150], parse_stars(stars), parse_duration(duration))
    except ValueError:
        return None
