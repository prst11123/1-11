"""Retrieve an NFT-specific, public JPEG for the exact t.me/nft slug.

Image retrieval is best-effort. This is not a Telegram Bot API metadata method:
Fragment's public image endpoint may be unavailable or change. Never fall
back to the fixed sample picture for a different gift.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlsplit

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .states import validate_gift_url

MAX_IMAGE_BYTES = 8 * 1024 * 1024


class GiftImageUnavailable(Exception):
    pass


def image_url(gift_url: str) -> str:
    # Validate URL instead of letting user supply arbitrary network destinations.
    slug = urlsplit(validate_gift_url(gift_url)).path.split("/")[-1]
    return f"https://nft.fragment.com/gift/{slug.lower()}.medium.jpg"


def jpeg_bytes(raw: bytes) -> bytes:
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise GiftImageUnavailable("Изображение слишком большое или пустое")
    try:
        with Image.open(BytesIO(raw)) as original:
            original.verify()
        with Image.open(BytesIO(raw)) as original:
            original = ImageOps.exif_transpose(original)
            original.thumbnail((1400, 1400))
            if original.mode not in {"RGB", "L"}:
                bg = Image.new("RGB", original.size, "white")
                if "A" in original.getbands():
                    bg.paste(original, mask=original.getchannel("A"))
                else:
                    bg.paste(original.convert("RGB"))
                original = bg
            output = BytesIO()
            original.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
            result = output.getvalue()
            if not result or len(result) > MAX_IMAGE_BYTES:
                raise GiftImageUnavailable("Размер изображения не поддерживается")
            return result
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise GiftImageUnavailable("Источник не вернул допустимое изображение") from e


async def fetch_gift_image(gift_url: str) -> bytes:
    url = image_url(gift_url)
    timeout = aiohttp.ClientTimeout(total=12, connect=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout, raise_for_status=False) as session:
            async with session.get(url, allow_redirects=False, headers={"Accept": "image/jpeg"}) as resp:
                if resp.status != 200 or not resp.headers.get("Content-Type", "").lower().startswith("image/"):
                    raise GiftImageUnavailable("Изображение этого NFT сейчас недоступно")
                if int(resp.headers.get("Content-Length") or 0) > MAX_IMAGE_BYTES:
                    raise GiftImageUnavailable("Изображение превышает лимит")
                raw = await resp.content.read(MAX_IMAGE_BYTES + 1)
                return await asyncio.to_thread(jpeg_bytes, raw)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise GiftImageUnavailable("Не удалось загрузить изображение NFT") from e
