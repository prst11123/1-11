"""Small official Bot API transport; no unofficial Telegram methods."""
from __future__ import annotations
import asyncio
import io
import json
import logging
from pathlib import Path
import aiohttp

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, method: str, status: int, description: str, retry_after: int | None = None):
        self.method, self.status, self.description, self.retry_after = method, status, description, retry_after
        super().__init__(f"{method}: Telegram {status}: {description}")


class Telegram:
    def __init__(self, token: str, default_image_path: str = "app/assets/fallback.png"):
        self._base = f"https://api.telegram.org/bot{token}/"
        self._image_path = Path(default_image_path)
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=22))

    async def close(self):
        if self._session:
            await self._session.close()

    async def api(self, method: str, **fields):
        if self._session is None:
            raise RuntimeError("Telegram session not initialized")
        data = {k:v for k,v in fields.items() if v is not None}
        for k in ("reply_markup", "allowed_updates", "results", "message_ids"):
            if k in data and not isinstance(data[k], str):
                data[k] = json.dumps(data[k], ensure_ascii=False)
        is_file = "__upload" in data
        upload = data.pop("__upload", None)
        for attempt in range(3):
            try:
                if is_file:
                    form = aiohttp.FormData()
                    for k,v in data.items():
                        form.add_field(k, str(v) if not isinstance(v,(dict,list)) else json.dumps(v))
                    form.add_field(upload[0], io.BytesIO(upload[1]), filename=upload[2], content_type=upload[3])
                    async with self._session.post(self._base+method, data=form) as resp:
                        result = await resp.json(content_type=None)
                else:
                    async with self._session.post(self._base+method, json=data) as resp:
                        result = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                # Do NOT retry sendPhoto/sendDocument: request may have succeeded remotely.
                if method in {"sendPhoto", "sendDocument", "sendMessage", "editMessageMedia", "editMessageCaption", "editMessageText", "deleteBusinessMessages"} or attempt == 2:
                    raise TelegramError(method, 0, f"Неопределённая ошибка сети: {type(exc).__name__}") from exc
                await asyncio.sleep(1+attempt)
                continue
            if result.get("ok"):
                return result.get("result")
            retry_after = (result.get("parameters") or {}).get("retry_after")
            if result.get("error_code") == 429 and retry_after and attempt < 2 and method not in {"sendPhoto", "sendDocument", "sendMessage", "editMessageMedia", "editMessageCaption", "editMessageText", "deleteBusinessMessages"}:
                await asyncio.sleep(min(int(retry_after),10))
                continue
            raise TelegramError(method, result.get("error_code", 0), result.get("description", "unknown error"), retry_after)
        raise TelegramError(method, 0, "Telegram request failed")

    async def send_message(self, chat_id: int, text: str, markup=None, business_id=None):
        return await self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup,
                              business_connection_id=business_id, disable_web_page_preview=True)

    async def send_media(self, chat_id: int, image_file_id: str | None, media_kind: str, caption: str,
                         markup=None, business_id=None, image_data: bytes | None = None,
                         reply_to_message_id: int | None = None):
        method = "sendDocument" if media_kind == "document" and image_file_id else "sendPhoto"
        field = "document" if method == "sendDocument" else "photo"
        opts = dict(chat_id=chat_id, caption=caption, parse_mode="HTML", reply_markup=markup,
                    business_connection_id=business_id)
        if reply_to_message_id is not None:
            opts["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
        if image_data is not None:
            opts["__upload"] = ("photo", image_data, "gift.jpg", "image/jpeg")
        elif image_file_id:
            opts[field] = image_file_id
        else:
            f = self._image_path
            mime = "image/jpeg" if f.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            opts["__upload"] = ("photo", f.read_bytes(), f.name, mime)
        return await self.api(method, **opts)

    async def edit_business_offer(self, chat_id: int, message_id: int, business_id: str,
                                  source_kind: str, image_data: bytes | None, image_file_id: str | None,
                                  caption: str, markup):
        """Try to transform the owner's exact outbound command in place.

        The API allows business-account messages not sent by the bot to be edited
        only inside Telegram's edit window. A transport timeout is ambiguous:
        callers must never blindly send a duplicate if it happens.
        """
        fields = dict(business_connection_id=business_id, chat_id=chat_id,
                      message_id=message_id, reply_markup=markup)
        if source_kind in {"photo", "document"}:
            return await self.api("editMessageCaption", caption=caption,
                                  parse_mode="HTML", **fields)
        media = {"type":"photo", "caption":caption, "parse_mode":"HTML"}
        if image_data is not None:
            media["media"] = "attach://gift"
            fields["__upload"] = ("gift", image_data, "gift.jpg", "image/jpeg")
        elif image_file_id:
            media["media"] = image_file_id
        else:
            raise ValueError("Нужен подтверждённый NFT-рисунок для редактирования")
        return await self.api("editMessageMedia", media=media, **fields)

    async def delete_business_source(self, connection_id: str, message_id: int):
        """Only called for the owner's exact command after replacement succeeds."""
        return await self.api("deleteBusinessMessages", business_connection_id=connection_id,
                              message_ids=[message_id])

    async def edit_test_caption(self, chat_id: int, message_id: int, caption: str, markup):
        return await self.api("editMessageCaption", chat_id=chat_id, message_id=message_id,
                              caption=caption, parse_mode="HTML", reply_markup=markup)

    async def answer_inline(self, query_id: str, results: list[dict]):
        return await self.api("answerInlineQuery", inline_query_id=query_id, results=results,
                              cache_time=0, is_personal=True)

    async def edit_inline_offer(self, inline_message_id: str, text: str, markup, photo: bool):
        if photo:
            return await self.api("editMessageCaption", inline_message_id=inline_message_id,
                                  caption=text, parse_mode="HTML", reply_markup=markup)
        return await self.api("editMessageText", inline_message_id=inline_message_id,
                              text=text, parse_mode="HTML", reply_markup=markup,
                              link_preview_options={"is_disabled":True})

    async def edit_caption(self, offer, caption, markup):
        return await self.api("editMessageCaption", business_connection_id=offer.business_connection_id,
                              chat_id=offer.recipient_chat_id, message_id=offer.telegram_message_id,
                              caption=caption, parse_mode="HTML", reply_markup=markup)

    async def answer_callback(self, callback_id: str, text: str="", alert=False):
        return await self.api("answerCallbackQuery", callback_query_id=callback_id, text=text[:195], show_alert=alert)

    async def edit_text(self, chat_id: int, message_id: int, text: str, markup=None):
        return await self.api("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                              parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

    async def get_business_connection(self, connection_id: str):
        return await self.api("getBusinessConnection", business_connection_id=connection_id)

    async def set_webhook(self, url: str, secret: str):
        return await self.api("setWebhook", url=url, secret_token=secret,
                              allowed_updates=["message", "callback_query", "business_connection", "business_message",
                                               "edited_business_message", "deleted_business_messages", "inline_query"],
                              drop_pending_updates=False, max_connections=20)
