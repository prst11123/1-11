"""Telegram updates, persistent wizard, role-checked admin actions and demo callbacks."""
from __future__ import annotations
import asyncio
import logging
import re
from datetime import timedelta
from types import SimpleNamespace
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .db import Database
from .store import Store, DomainError
from .telegram import Telegram, TelegramError
from .states import (WAIT_URL,WAIT_STARS,WAIT_EXPIRATION,WAIT_IMAGE,WAIT_NAME,WAIT_TARGET,PREVIEW,ADMIN_INPUT,
                     utcnow,validate_gift_url,default_gift_name,parse_stars,parse_duration)
from . import keyboards as kb
from . import render as rnd
from .services.transfer import DemoTransferGateway
from .quick_offer import parse_quick_offer
from .gift_images import fetch_gift_image, GiftImageUnavailable

log = logging.getLogger(__name__)


class AppHandler:
    def __init__(self, cfg: Settings, store: Store, tg: Telegram, transfer_gateway=None):
        self.cfg,self.store,self.tg = cfg,store,tg
        self.transfer_gateway = transfer_gateway or DemoTransferGateway()

    async def db(self, name: str, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store,name), *args, **kwargs)

    async def dispatch(self, update: dict):
        update_id=update.get("update_id")
        if not isinstance(update_id,int):return
        try:
            accepted=await self.db("register_update",update_id)
        except IntegrityError:
            return
        if not accepted:return
        try:
            if "business_connection" in update:
                bc=update["business_connection"]
                await self.db("connection_update",bc)
                log.info("business_connection_updated",extra={"event":"BUSINESS_UPDATED","user_id":(bc.get("user") or {}).get("id"),"business_connection_id":bc.get("id")})
            elif "business_message" in update or "edited_business_message" in update:
                msg=update.get("business_message") or update.get("edited_business_message")
                conn_id=msg.get("business_connection_id")
                if conn_id:
                    # On reconnection a Business message may arrive before the connection update.
                    try:
                        remote=await self.tg.get_business_connection(conn_id)
                        await self.db("connection_update",remote)
                    except TelegramError as e:
                        log.warning("business_connection_refresh_failed id=%s status=%s",conn_id,e.status)
                    discovered=await self.db("business_incoming",msg)
                    if discovered:
                        log.info("business_chat_observed",extra={"event":"BUSINESS_CHAT_OBSERVED","user_id":(msg.get("from") or {}).get("id"),"business_connection_id":conn_id})
                    # Treat only a NEW owner's message as a quick-offer command;
                    # never create offers from recipient messages or edited updates.
                    if "business_message" in update:
                        await self.on_business_quick_offer(msg)
            elif "deleted_business_messages" in update:
                await self.db("business_deleted",update["deleted_business_messages"])
            elif "message" in update:
                await self.on_message(update["message"])
            elif "callback_query" in update:
                await self.on_callback(update["callback_query"])
        except Exception:
            log.exception("update_failed update_id=%s",update_id)
            # Drop the processed flag so Telegram can retry only if Telegram actually retransmits.
            # Most domain operations remain idempotent even after a partial update.
            await self.db("forget_update",update_id)
            raise

    async def on_business_quick_offer(self, msg: dict):
        """Create an Offer in the current chat from an owner-authored message.

        Text and photo captions may contain exactly:
            https://t.me/nft/PlushPepe-123
            1000
            15м
        """
        if (msg.get("chat") or {}).get("type") != "private":
            return
        raw = (msg.get("text") or msg.get("caption") or "").strip()
        command = parse_quick_offer(raw)
        if not command:
            return
        actor = (msg.get("from") or {}).get("id")
        connection_id = msg.get("business_connection_id")
        chat_id = (msg.get("chat") or {}).get("id")
        source_id = msg.get("message_id")
        if not (isinstance(actor, int) and isinstance(chat_id, int)
                and isinstance(source_id, int) and connection_id):
            return
        # Don't execute stale updates that may be replayed after a webhook outage.
        from datetime import datetime, timezone
        sent_at = datetime.fromtimestamp(int(msg.get("date") or 0), timezone.utc)
        if not (utcnow() - timedelta(minutes=10) <= sent_at <= utcnow() + timedelta(minutes=2)):
            return
        existing = await self.db("business_offer_by_source", connection_id, chat_id, source_id)
        if existing:
            return
        # Confirm origin before downloading anything or writing an offer.
        allowed = await self.db("can_issue_business_command", actor, connection_id, chat_id)
        if not allowed:
            return
        photos = msg.get("photo") or []
        attachment = (msg.get("document") or {})
        supplied = photos[-1].get("file_id") if photos else (
            attachment.get("file_id") if str(attachment.get("mime_type", "")).startswith("image/") else None)
        media_kind = "document" if not photos and supplied else "photo"
        image_data = None
        if not supplied:
            try:
                image_data = await fetch_gift_image(command.gift_url)
            except GiftImageUnavailable as e:
                # Don't substitute a different NFT image or falsely confirm sending.
                await self._notify_owner(actor,
                    f"⚠️ Не получилось загрузить изображение <code>{rnd.h(command.gift_url)}</code>: {rnd.h(e)}. "
                    "Отправьте в тот же Business-чат изображение нужного NFT с теми же тремя строками в подписи.")
                return
        payload = {"gift_url": command.gift_url, "gift_name": command.gift_name,
                   "stars": command.stars, "duration": command.duration,
                   "image_file_id": supplied, "media_kind": media_kind}
        try:
            o = await self.db("create_business_chat_offer", actor, connection_id, chat_id, source_id, payload)
        except DomainError as e:
            await self._notify_owner(actor, f"⚠️ Офер не создан: {rnd.h(e)}")
            return
        if o.delivery_status != "sending":
            return
        try:
            await self.send_offer(o, image_data=image_data, reply_to_message_id=source_id)
        except (DomainError, TelegramError) as e:
            await self._notify_owner(actor, f"❌ Не удалось отправить DEMO Offer: {rnd.h(e)}")

    async def _notify_owner(self, user_id: int, text: str):
        try:
            await self.say(user_id, text)
        except TelegramError:
            log.warning("business_owner_notification_failed", extra={"user_id": user_id})

    async def say(self, chat_id: int, text: str, markup=None):
        return await self.tg.send_message(chat_id,rnd.branded(text),markup)

    async def on_message(self, m:dict):
        if (m.get("chat") or {}).get("type") != "private":return
        actor=m.get("from") or {}
        uid=actor.get("id")
        if not uid:return
        text=(m.get("text") or m.get("caption") or "").strip()
        started=text.split(" ")[0].split("@")[0] == "/start"
        user=await self.db("touch_user", actor, started)
        if started:
            if user.blocked:
                await self.say(uid,"⛔ Ваш аккаунт заблокирован")
            elif user.allowed:
                await self.say(uid,"🧪 <b>DEMO NFT Gift Offer</b>\n\nСоздание и отправка предложений через Telegram Business. Реальных Stars или NFT-транзакций нет.",
                               kb.main_menu(user.role in {"owner","admin"}))
            else:
                await self.say(uid,f"🔐 Доступ ограничен whitelist.\nВаш Telegram ID: <code>{uid}</code>\nПередайте ID администратору.")
            return
        if text in {"/cancel", "Отмена", "❌ Отмена"}:
            await self.db("clear_flow",uid)
            await self.say(uid,"Создание отменено.",kb.main_menu(user.role in {"owner","admin"}))
            return
        if user.blocked:
            await self.say(uid,"⛔ Ваш аккаунт заблокирован")
            return
        if not user.allowed:
            await self.say(uid,"🔐 Нет доступа к боту. Напишите /start для получения Telegram ID.")
            return
        if text.split(" ")[0].split("@")[0] == "/admin" or text == "⚙️ Админ-панель":
            if user.role not in {"admin","owner"}:
                await self.say(uid,"Недостаточно прав администратора")
            else:
                await self.show_admin(uid)
            return
        state,payload=await self.db("flow",uid)
        if state==ADMIN_INPUT:
            await self.admin_input(uid,text,payload)
            return
        if state=="ADMIN_CONTACT_INPUT":
            await self.admin_contact_input(uid,text)
            return
        if state in {WAIT_URL,WAIT_STARS,WAIT_EXPIRATION,WAIT_IMAGE,WAIT_NAME,WAIT_TARGET}:
            await self.wizard_message(uid,m,state,payload)
            return
        if text in {"🎁 Создать офер","/create"}:
            await self.start_wizard(uid)
        elif text in {"📋 Мои оферы","/offers"}:
            await self.show_my_offers(uid,0)
        elif text in {"💼 Business подключения","/business"}:
            await self.show_connections(uid)
        elif text in {"📊 Статистика","/stats"}:
            if user.role in {"admin","owner"}:
                await self.say(uid,rnd.stats_text(await self.db("stats")))
            else:
                stats=await self.db("personal_stats",uid)
                statuses="\n".join(f"{rnd.STATUS_RU.get(k,k)}: {v}" for k,v in stats["statuses"].items())
                await self.say(uid,f"📊 <b>Моя статистика</b>\nСоздано: {stats['total']}\nОтправлено: {stats['sent']}\n{statuses}")
        elif text in {"❓ Помощь","/help"}:
            help_text=("🧪 <b>Помощь · DEMO</b>\n\n<b>Новый способ: прямо в Business-чате</b>\n"
                       "Отправьте собеседнику одно сообщение из трёх строк:\n"
                       "<code>https://t.me/nft/PlushPepe-123</code>\n<code>1000</code>\n<code>15м</code>\n\n"
                       "Бот отправит карточку в тот же чат. Если фото NFT не удалось получить автоматически, "
                       "пришлите фото NFT с этими строками в подписи.\n\n"
                       "Старый способ: «Создать офер» в меню бота.\n\n"
                       "У Business-бота должно быть can_reply, а у собеседника — входящее сообщение "
                       "в последние 24 часа. Stars и NFT не переводятся.")
            contact_username, _ = await self.db("display_contact")
            if contact_username:
                help_text += (f"\n\n👤 Контакт для вопросов по DEMO: "
                              f"@{rnd.h(contact_username)} (не для перевода NFT).")
            await self.say(uid,help_text)
        else:
            await self.say(uid,"Выберите действие в меню или отправьте /help.",kb.main_menu(user.role in {"admin","owner"}))

    async def start_wizard(self,uid:int):
        conns=await self.db("connections",uid)
        if not any(c.active for c in conns):
            await self.say(uid,"Сначала подключите бота к Telegram Business. После подключения появится Business Connection. Затем получатель должен написать в доступный Business Chat.")
            return
        await self.db("save_flow",uid,WAIT_URL,{})
        await self.say(uid,"🎁 <b>Новый NFT Gift Offer</b>\n\nШаг 1/6: пришлите NFT-ссылку, например <code>https://t.me/nft/PlushPepe-123</code>, или «Авто» для DEFAULT_GIFT_URL.",kb.cancel_keyboard())

    async def wizard_message(self,uid:int,msg:dict,state:str,p:dict):
        text=(msg.get("text") or "").strip()
        is_edit=bool(p.get("edit_mode"))
        try:
            if state==WAIT_URL:
                p["gift_url"]=validate_gift_url(self.cfg.default_gift_url if text.lower() in {"авто", "auto"} else text)
                if not is_edit:
                    await self.db("save_flow",uid,WAIT_STARS,p)
                    return await self.say(uid,"Шаг 2/6: введите количество Stars (целое число, от 1 до 1 000 000 000 000) или «Авто».",kb.cancel_keyboard())
            elif state==WAIT_STARS:
                p["stars"]=self.cfg.default_stars if text.lower() in {"авто","auto"} else parse_stars(text)
                if not is_edit:
                    await self.db("save_flow",uid,WAIT_EXPIRATION,p)
                    return await self.say(uid,"Шаг 3/6: выберите срок или напишите минуты (1–10080). Можно «Авто».",kb.duration_keyboard())
            elif state==WAIT_EXPIRATION:
                p["duration"]=self.cfg.default_expiration if text.lower() in {"авто","auto"} else parse_duration(text)
                if not is_edit:
                    await self.db("save_flow",uid,WAIT_IMAGE,p)
                    return await self.say(uid,"Шаг 4/6: пришлите фотографию, изображение документом или напишите «Пропустить» для стандартного DEMO-изображения.",kb.cancel_keyboard())
            elif state==WAIT_IMAGE:
                photo=(msg.get("photo") or [])
                doc=msg.get("document") or {}
                if photo:
                    p["image_file_id"]=photo[-1]["file_id"]
                    p["media_kind"]="photo"
                elif (doc.get("mime_type") or "").startswith("image/"):
                    p["image_file_id"]=doc["file_id"]
                    p["media_kind"]="document"
                elif text.lower() in {"пропустить","skip","-"}:
                    p["image_file_id"]=None
                    p["media_kind"]="photo"
                else:
                    raise DomainError("Пришлите фото, image-документ или «Пропустить»")
                if not is_edit:
                    await self.db("save_flow",uid,WAIT_NAME,p)
                    return await self.say(uid,"Шаг 5/6: введите название NFT Gift или «Авто» (по ссылке).",kb.cancel_keyboard())
            elif state==WAIT_NAME:
                name=(self.cfg.default_gift_name if p["gift_url"]==self.cfg.default_gift_url else default_gift_name(p["gift_url"])) if text.lower() in {"авто","auto"} else text
                if not (1<=len(name)<=150):raise DomainError("Название должно содержать от 1 до 150 символов")
                p["gift_name"]=name
                if not is_edit:
                    await self.db("save_flow",uid,WAIT_TARGET,p)
                    return await self.show_target_choices(uid,0)
            elif state==WAIT_TARGET:
                raise DomainError("Выберите Target кнопкой под сообщением")
            if is_edit:
                p.pop("edit_mode",None)
                await self.db("save_flow",uid,PREVIEW,p)
                return await self.show_preview(uid,p)
        except (ValueError,DomainError) as e:
            await self.say(uid,"⚠️ "+rnd.h(str(e))+"\nПопробуйте снова или нажмите Отмена.",kb.cancel_keyboard())

    async def show_target_choices(self,uid,page=0):
        total,rows=await self.db("known_chats",uid,page,8)
        info=("🎯 <b>Шаг 6/6: выбор Target</b>\n\n🟢 = есть право can_reply и свежий входящий чат.\n"
              "🔴 = недоступно.\n\nЕсли установлен TARGET_CHAT_ID в Railway, он имеет приоритет над ручным выбором.")
        await self.say(uid,info,kb.target_keyboard(rows,page,total))

    async def show_preview(self,uid,payload):
        try:
            target=await self.db("resolve_target",uid,payload.get("target_chat_pk"))
            caption=rnd.preview_caption(payload,target)
            await self.tg.send_media(uid,payload.get("image_file_id"),payload.get("media_kind","photo"),
                                     caption,kb.preview_keyboard())
        except (ValueError,DomainError,TelegramError) as e:
            await self.say(uid,f"⚠️ Preview: {rnd.h(e)}\nВыберите Target повторно.")
            await self.db("save_flow",uid,WAIT_TARGET,payload)
            await self.show_target_choices(uid)

    async def send_offer(self,offer, image_data: bytes | None = None, reply_to_message_id: int | None = None):
        try:
            await self.db("refresh_send_authorization",offer.id)
        except DomainError as exc:
            await self.db("mark_failed",offer.id,str(exc))
            raise
        try:
            active_offer=SimpleNamespace(**{**vars(offer),"status":"active"})
            opts = {}
            if image_data is not None:
                opts["image_data"] = image_data
            if reply_to_message_id is not None:
                opts["reply_to_message_id"] = reply_to_message_id
            result=await self.tg.send_media(offer.recipient_chat_id,offer.gift_image_file_id,offer.media_kind,
                                            rnd.offer_caption(active_offer),kb.offer_keyboard(active_offer),
                                            business_id=offer.business_connection_id, **opts)
        except TelegramError as exc:
            if exc.status==0:
                await self.db("mark_unknown",offer.id,str(exc))
            else:
                await self.db("mark_failed",offer.id,str(exc))
            raise
        # If DB commit fails after Telegram succeeded, startup reconciliation marks the delivery unknown.
        photo = result.get("photo") or []
        image_file_id = photo[-1].get("file_id") if photo and isinstance(photo[-1],dict) else None
        saved=await self.db("mark_sent",offer.id,int(result["message_id"]),image_file_id)
        log.info("offer_sent",extra={"event":"OFFER_SENT","user_id":saved.creator_id,"offer_id":saved.id,"business_connection_id":saved.business_connection_id})
        return saved

    async def on_callback(self,c:dict):
        uid=(c.get("from") or {}).get("id")
        cid=c.get("id")
        data=c.get("data") or ""
        if not uid or not cid:return
        await self.db("touch_user",c["from"],False)
        try:
            registered=await self.db("register_callback",cid)
        except IntegrityError:
            registered=False
        if not registered:
            return await self.tg.answer_callback(cid,"Уже обработано")
        try:
            if data.startswith("offer:"):
                return await self.offer_callback(uid,cid,data,c)
            if data.startswith("admin:"):
                if not await self.db("is_admin",uid):
                    raise DomainError("Требуются права администратора")
                return await self.admin_callback(uid,cid,data,c)
            if not await self.db("can_create",uid):
                raise DomainError("Нет доступа")
            if data.startswith("flow:"):
                return await self.flow_callback(uid,cid,data)
            if data.startswith("mine:"):
                return await self.mine_callback(uid,cid,data)
            await self.tg.answer_callback(cid,"Неизвестная кнопка",True)
        except (DomainError,ValueError,TelegramError) as e:
            log.warning("callback_denied user_id=%s callback=%s reason=%s",uid,data,str(e)[:200])
            try:await self.tg.answer_callback(cid,str(e),True)
            except TelegramError:log.exception("callback_answer_failed")
        except Exception:
            log.exception("callback_failed user_id=%s",uid)
            try:await self.tg.answer_callback(cid,"Ошибка. Попробуйте снова или обратитесь к администратору",True)
            except TelegramError:pass

    async def flow_callback(self,uid:int,cid:str,data:str):
        if data=="flow:cancel":
            await self.db("clear_flow",uid)
            return await self.tg.answer_callback(cid,"Отменено")
        state,p=await self.db("flow",uid)
        if state is None:raise DomainError("Сессия создания не найдена. Начните заново")
        if data.startswith("flow:duration:"):
            if state!=WAIT_EXPIRATION:raise DomainError("Сейчас нельзя выбрать время")
            p["duration"]=parse_duration(data.rsplit(":",1)[1])
            if p.get("edit_mode"):
                p.pop("edit_mode",None)
                await self.db("save_flow",uid,PREVIEW,p)
                await self.tg.answer_callback(cid,"Изменено")
                return await self.show_preview(uid,p)
            await self.db("save_flow",uid,WAIT_IMAGE,p)
            await self.tg.answer_callback(cid,"Срок выбран")
            return await self.say(uid,"Шаг 4/6: пришлите изображение или «Пропустить».",kb.cancel_keyboard())
        if data.startswith("flow:targets:"):
            if state!=WAIT_TARGET:raise DomainError("Сейчас нельзя выбирать Target")
            await self.tg.answer_callback(cid)
            return await self.show_target_choices(uid,int(data.split(":")[-1]))
        if data.startswith("flow:target:"):
            if state!=WAIT_TARGET:raise DomainError("Сейчас нельзя выбирать Target")
            sel=data.rsplit(":",1)[1]
            if sel=="auto":
                p.pop("target_chat_pk",None)
                await self.db("resolve_target",uid,None)
            else:
                p["target_chat_pk"]=int(sel)
                await self.db("resolve_target",uid,p["target_chat_pk"])
            p.pop("edit_mode",None)
            await self.db("save_flow",uid,PREVIEW,p)
            await self.tg.answer_callback(cid,"Target проверен")
            return await self.show_preview(uid,p)
        if data=="flow:preview":
            await self.db("save_flow",uid,PREVIEW,p)
            await self.tg.answer_callback(cid)
            return await self.show_preview(uid,p)
        if data=="flow:edit":
            if state!=PREVIEW:raise DomainError("Preview устарел")
            await self.tg.answer_callback(cid)
            return await self.say(uid,"Что изменить?",kb.edit_keyboard())
        if data.startswith("flow:edit:"):
            if state!=PREVIEW:raise DomainError("Preview устарел")
            field=data.rsplit(":",1)[1]
            mapping={"url":WAIT_URL,"stars":WAIT_STARS,"duration":WAIT_EXPIRATION,
                     "image":WAIT_IMAGE,"name":WAIT_NAME,"target":WAIT_TARGET}
            if field not in mapping:raise DomainError("Неизвестное поле")
            p["edit_mode"]=True
            await self.db("save_flow",uid,mapping[field],p)
            await self.tg.answer_callback(cid)
            if field=="target":return await self.show_target_choices(uid)
            await self.say(uid,{"url":"Введите новую NFT-ссылку", "stars":"Введите новую сумму Stars",
                                "duration":"Введите новое время в минутах (либо выберите ниже)",
                                "image":"Пришлите новое изображение или «Пропустить»",
                                "name":"Введите новое название"}[field],kb.duration_keyboard() if field=="duration" else kb.cancel_keyboard())
            return
        if data=="flow:send":
            if state!=PREVIEW:raise DomainError("Preview устарел")
            target=await self.db("resolve_target",uid,p.get("target_chat_pk"))
            # Refresh authority from Telegram before send, not just stale local rights.
            remote=await self.tg.get_business_connection(target["connection_id"])
            await self.db("connection_update",remote)
            offer=await self.db("create_offer",uid,p)
            await self.db("clear_flow",uid)
            await self.tg.answer_callback(cid,"Отправляем в Business Chat…")
            try:
                result=await self.send_offer(offer)
            except (DomainError,TelegramError) as e:
                fresh=await self.db("offer",offer.id)
                if fresh.delivery_status=="unknown":
                    await self.say(uid,f"⚠️ Неясный результат Telegram API для Offer #{offer.id}. Проверьте чат и журнал перед повторной отправкой. Автоматическое дублирование запрещено.")
                else:
                    await self.say(uid,f"❌ Ошибка отправки Offer #{offer.id}: {rnd.h(e)}\nПовтор можно выполнить через «Мои оферы» при доступном Target.")
                return
            return await self.say(uid,f"✅ <b>DEMO Offer #{result.id} отправлен</b>\nПолучатель: <code>{result.recipient_user_id}</code>\nTelegram message ID: <code>{result.telegram_message_id}</code>\nИстечёт: {rnd.expiry_string(result.expires_at)}")
        raise DomainError("Неизвестная операция")

    async def offer_callback(self,uid:int,cid:str,data:str,c:dict):
        parts=data.split(":")
        if len(parts)!=3:raise DomainError("Некорректные callback-данные")
        _,action,id_text=parts
        offer_id=int(id_text)
        o=await self.db("offer",offer_id)
        if o is None:raise DomainError("Offer не найден")
        # For forwarded/stale messages, the caller must be in the original Business Chat.
        message=c.get("message") or {}
        message_chat=(message.get("chat") or {}).get("id")
        if message_chat != o.recipient_chat_id or message.get("message_id") != o.telegram_message_id:
            raise DomainError("Кнопка не относится к исходному Business-сообщению")
        if action=="instructions":
            o=await self.db("open_instructions",offer_id,uid)
            # Do not put contact information or branding in the Business chat.
            info=rnd.instructions()
            try:
                await self.tg.send_message(o.recipient_chat_id,rnd.h(info),business_id=o.business_connection_id)
                return await self.tg.answer_callback(cid,"Инструкция отправлена отдельным сообщением")
            except TelegramError:
                return await self.tg.answer_callback(cid,info[:195],True)
        if action not in {"accept","decline","transfer"}:
            raise DomainError("Неизвестная кнопка Offer")
        if action == "transfer":
            await self.transfer_gateway.validate_transfer_request(o,uid)
        updated,expired=await self.db("offer_transition",offer_id,uid,action)
        log.info("offer_action_saved",extra={"event":"OFFER_EXPIRED" if expired else "OFFER_"+action.upper(),
                                            "user_id":uid,"offer_id":offer_id,"business_connection_id":updated.business_connection_id})
        await self.tg.answer_callback(cid,"Срок истёк" if expired else "DEMO: действие сохранено")
        await self.sync_offer(updated)

    async def sync_offer(self,o):
        if not o.telegram_message_id or o.delivery_status != "sent":return
        try:
            await self.tg.edit_caption(o,rnd.offer_caption(o),kb.offer_keyboard(o))
            await self.db("mark_synced",o.id,o.version)
        except TelegramError as e:
            if "message is not modified" in e.description.lower():
                await self.db("mark_synced",o.id,o.version)
                return
            log.warning("offer_message_edit_failed offer_id=%s business_connection_id=%s status=%s",o.id,o.business_connection_id,e.status)
            if e.status in {400,403}:
                await self.db("permanent_sync_error",o.id,str(e))

    async def mine_callback(self,uid:int,cid:str,data:str):
        parts=data.split(":")
        if len(parts)<3:raise DomainError("Неверная кнопка")
        if parts[1]=="page":
            await self.tg.answer_callback(cid)
            return await self.show_my_offers(uid,int(parts[2]))
        id_=int(parts[2])
        o=await self.db("offer",id_)
        if not o or o.creator_id!=uid:raise DomainError("Это не ваш Offer")
        if parts[1]=="details":
            await self.tg.answer_callback(cid)
            text=(f"🎁 <b>Offer #{o.id}</b>\n{rnd.h(o.gift_name)}\n{rnd.h(o.gift_url)}\n"
                  f"⭐ {o.stars_amount} Stars\n🎯 Chat: <code>{o.recipient_chat_id}</code>\n"
                  f"📍 {rnd.STATUS_RU.get(o.status,o.status)}\n🚚 {rnd.h(o.delivery_status)}\n"
                  f"⌛ {rnd.expiry_string(o.expires_at)}")
            buttons=[]
            if o.status=="active":buttons.append([kb.btn("❌ Отменить",f"mine:cancel:{id_}")])
            if o.status=="draft" and o.delivery_status=="failed":buttons.append([kb.btn("🔁 Повторить отправку",f"mine:retry:{id_}")])
            buttons.append([kb.btn("📋 Мои оферы","mine:page:0")])
            return await self.say(uid,text,{"inline_keyboard":buttons})
        if parts[1]=="cancel":
            o=await self.db("cancel_offer",id_,uid)
            await self.tg.answer_callback(cid,"Отменено")
            await self.sync_offer(o)
            return await self.say(uid,f"Offer #{o.id} отменён.")
        if parts[1]=="retry":
            o=await self.db("retry_send",id_,uid)
            await self.tg.answer_callback(cid,"Пробуем отправить…")
            try:
                await self.send_offer(o)
                return await self.say(uid,f"✅ Offer #{o.id} отправлен")
            except (DomainError,TelegramError) as e:
                return await self.say(uid,f"⚠️ Не удалось отправить Offer #{o.id}: {rnd.h(e)}")
        raise DomainError("Неизвестная кнопка")

    async def show_my_offers(self,uid:int,page:int):
        total,rows=await self.db("offers_by_creator",uid,page,8,False)
        buttons=[]
        for o in rows:
            buttons.append([kb.btn(f"#{o.id} · {rnd.STATUS_RU.get(o.status,o.status)} · {o.stars_amount}⭐",f"mine:details:{o.id}")])
        if page>0:buttons.append([kb.btn("◀️ Назад",f"mine:page:{page-1}")])
        if (page+1)*8<total:buttons.append([kb.btn("▶️ Далее",f"mine:page:{page+1}")])
        await self.say(uid,f"📋 <b>Мои оферы</b> · Всего: {total}",{"inline_keyboard":buttons} if buttons else None)

    async def show_connections(self,uid:int):
        conns=await self.db("connections",uid)
        out=["💼 <b>Business Connections</b>"]
        for c in conns[:15]:
            out.append(f"\n{'🟢' if c.active else '🔴'} <code>{rnd.h(c.business_connection_id)}</code>"
                       f"\nВладелец: {rnd.h(c.owner_username or c.owner_user_id)}"
                       f"\ncan_reply: {bool(c.permissions.get('can_reply'))}")
        if not conns:out.append("\nНет подключений. Подключите бота в Telegram → Business → Chatbots.")
        total,rows=await self.db("known_chats",uid,0,5)
        out.append(f"\nОбнаруженных Business Chats: {total}")
        for ch,conn,enabled in rows:
            out.append(f"{'🟢' if enabled else '🔴'} {rnd.h(ch.first_name or ch.username or 'Contact')} · <code>{ch.chat_id}</code>")
        await self.say(uid,"\n".join(out))

    async def show_admin(self,uid:int):
        await self.say(uid,"⚙️ <b>Админ-панель · DEMO NFT Gift Offers</b>",kb.admin_keyboard())

    async def admin_input(self,uid:int,text:str,p:dict):
        try:
            target=int(text)
            if target<=0:raise ValueError
            action=p["admin_action"]
            u=await self.db("set_user_access",uid,target,action)
            await self.db("clear_flow",uid)
            log.info("admin_user_action",extra={"event":"ADMIN_USER_"+action.upper(),"user_id":uid})
            await self.say(uid,f"✅ Готово: {action} · <code>{u.telegram_id}</code> · role={u.role}",kb.admin_keyboard())
        except ValueError:
            await self.say(uid,"⚠️ Введите положительный числовой Telegram ID, или /cancel")
        except DomainError as e:
            await self.say(uid,f"⚠️ {rnd.h(e)}")

    async def admin_contact_input(self, uid: int, text: str):
        """Only owner may update the DEMO information contact."""
        try:
            if text.strip().lower() in {"сброс", "reset", "-"}:
                username = None
            else:
                username = text.strip()
            current, source = await self.db("set_display_contact", uid, username)
            await self.db("clear_flow", uid)
            display = f"@{rnd.h(current)}" if current else "не указан"
            await self.say(uid, f"✅ Контакт обновлён: {display}\nИсточник: {source}\n"
                                "Контакт отображается только для справок по DEMO, не как адрес NFT-передачи.",
                           kb.inline([kb.btn("↩️ Настройки контакта", "admin:contact")]))
        except DomainError as exc:
            await self.say(uid, f"⚠️ {rnd.h(exc)}\nВведите @username или «Сброс». Отмена — /cancel")

    async def admin_callback(self,uid:int,cid:str,data:str,c:dict):
        parts=data.split(":")
        action=parts[1] if len(parts)>1 else ""
        await self.tg.answer_callback(cid)
        if action=="panel":
            return await self.show_admin(uid)
        if action=="home":
            return await self.say(uid,"Главное меню",kb.main_menu(admin=True))
        if action=="stats":
            return await self.say(uid,rnd.stats_text(await self.db("stats")),kb.inline([kb.btn("↩️ Админ-панель","admin:panel")]))
        if action=="business":
            return await self.show_connections(uid)
        if action=="contact":
            username, source = await self.db("display_contact")
            user = await self.db("user", uid)
            message=("👤 <b>Контакт по DEMO-оферам</b>\n"
                     f"Текущее значение: <code>@{rnd.h(username)}</code>\n" if username else
                     "👤 <b>Контакт по DEMO-оферам</b>\nТекущее значение: не указан\n")
            message += f"Источник: <b>{rnd.h(source)}</b>\n"
            message += "Контакт предназначен только для справок. Он не является адресом передачи NFT."
            rows=[]
            if user and user.role=="owner":
                rows.append([kb.btn("✏️ Изменить юз", "admin:contactedit"),
                             kb.btn("♻️ Сброс к Railway", "admin:contactreset")])
            rows.append([kb.btn("↩️ Админ-панель", "admin:panel")])
            return await self.say(uid,message,{"inline_keyboard":rows})
        if action=="contactedit":
            user = await self.db("user", uid)
            if not user or user.role!="owner":
                raise DomainError("Изменение контакта доступно только владельцу бота")
            await self.db("save_flow", uid, "ADMIN_CONTACT_INPUT", {})
            return await self.say(uid,"Отправьте @username контакта для справок по DEMO "
                                       "(5–32 латинских буквы, цифры или _).\n"
                                       "Для отмены: /cancel; для Railway: «Сброс».")
        if action=="contactreset":
            current, source = await self.db("set_display_contact", uid, None)
            return await self.say(uid, f"✅ Контакт сброшен. Текущий: {rnd.h('@'+current if current else '—')} "
                                       f"({rnd.h(source)}).", kb.inline([kb.btn("↩️ Контакт", "admin:contact")]))
        if action=="target":
            r=await self.db("describe_target",uid)
            message=("🎯 <b>Текущий Target</b>\n"
                     f"Источник: <b>{rnd.h(r.get('source','не указан'))}</b>\n"
                     f"Railway TARGET_CHAT_ID: <code>{self.cfg.target_chat_id or '—'}</code>\n"
                     f"Railway TARGET_USER_ID: <code>{self.cfg.target_user_id or '—'}</code>\n"
                     f"Railway TARGET_USERNAME: <code>{rnd.h(self.cfg.target_username or '—')}</code>\n")
            if r.get("available"):
                message+=(f"\n🟢 Доступен\nUser ID: <code>{r['user_id']}</code>\nChat ID: <code>{r['chat_id']}</code>\n"
                          f"Username: {rnd.h(r.get('username') or '—')}\nBusiness Connection: <code>{rnd.h(r['connection_id'])}</code>\n"
                          f"Входящее сообщение: {rnd.expiry_string(r['last_incoming_at'])}")
            else:
                message+="\n🔴 " + rnd.h(r.get("error","Не найден"))
            return await self.say(uid,message,kb.inline([kb.btn("↩️ Админ-панель","admin:panel")]))
        if action=="input":
            if len(parts)!=3 or parts[2] not in {"allow","revoke","block","unblock","promote","demote"}:
                raise DomainError("Неизвестное административное действие")
            await self.db("save_flow",uid,ADMIN_INPUT,{"admin_action":parts[2]})
            return await self.say(uid,f"Введите Telegram ID для действия <b>{parts[2]}</b>.\nОтмена — /cancel")
        if action=="admins":
            page=max(0,int(parts[2])) if len(parts)>2 else 0
            total,all_users=await self.db("admins",page,8)
            lines=[f"🛡 <b>Администраторы</b> · всего {total}"]+[f"{rnd.h(x.role)} · <code>{x.telegram_id}</code>" for x in all_users]
            nav=[]
            if page:nav.append(kb.btn("◀️",f"admin:admins:{page-1}"))
            if (page+1)*8<total:nav.append(kb.btn("▶️",f"admin:admins:{page+1}"))
            rows=[nav] if nav else []
            rows += [[kb.btn("➕ Добавить Admin","admin:input:promote"),kb.btn("➖ Убрать Admin","admin:input:demote")],
                     [kb.btn("↩️ Назад","admin:panel")]]
            return await self.say(uid,"\n".join(lines),{"inline_keyboard":rows})
        if action=="users":
            page=max(0,int(parts[2]))
            total,items=await self.db("get_users",page,8)
            text=f"👥 <b>Пользователи</b> · {total}"
            buttons=[[kb.btn(f"{u.username or u.telegram_id} · {u.role} · {'✅' if u.allowed else '❌'} {'⛔' if u.blocked else ''}",f"admin:user:{u.telegram_id}")] for u in items]
            nav=[]
            if page:nav.append(kb.btn("◀️",f"admin:users:{page-1}"))
            if (page+1)*8<total:nav.append(kb.btn("▶️",f"admin:users:{page+1}"))
            if nav:buttons.append(nav)
            buttons.append([kb.btn("↩️ Админ-панель","admin:panel")])
            return await self.say(uid,text,{"inline_keyboard":buttons})
        if action=="user":
            if len(parts)!=3:raise DomainError("Не указан ID")
            return await self.show_user(uid,int(parts[2]))
        if action=="useract":
            if len(parts)!=4:raise DomainError("Неверное действие")
            act,target=parts[2],int(parts[3])
            await self.db("set_user_access",uid,target,act)
            return await self.show_user(uid,target)
        if action=="offers":
            page=max(0,int(parts[2]))
            total,items=await self.db("offers_by_creator",uid,page,8,True)
            buttons=[[kb.btn(f"#{o.id} · {o.creator_id} · {rnd.STATUS_RU.get(o.status,o.status)}",f"admin:offerdetail:{o.id}")] for o in items]
            nav=[]
            if page:nav.append(kb.btn("◀️",f"admin:offers:{page-1}"))
            if (page+1)*8<total:nav.append(kb.btn("▶️",f"admin:offers:{page+1}"))
            if nav:buttons.append(nav)
            buttons.append([kb.btn("↩️ Админ-панель","admin:panel")])
            return await self.say(uid,f"🎁 <b>Все Offers</b> · {total}",{"inline_keyboard":buttons})
        if action=="offerdetail":
            o=await self.db("offer",int(parts[2]))
            if not o:raise DomainError("Offer не найден")
            rows=[]
            if o.status=="active":rows.append([kb.btn("❌ Отменить Offer",f"admin:offercancel:{o.id}")])
            rows.append([kb.btn("↩️ Offers","admin:offers:0")])
            return await self.say(uid,(f"🎁 <b>Offer #{o.id}</b> · {rnd.STATUS_RU.get(o.status,o.status)}\n"
                                       f"Creator: <code>{o.creator_id}</code>\nRecipient: <code>{o.recipient_user_id}</code>\n"
                                       f"Business Chat: <code>{o.recipient_chat_id}</code>\n"
                                       f"Connection: <code>{rnd.h(o.business_connection_id)}</code>\n"
                                       f"Gift: {rnd.h(o.gift_name)}\nStars: {o.stars_amount}\n"
                                       f"Expires: {rnd.expiry_string(o.expires_at)}\nDelivery: {rnd.h(o.delivery_status)}"),{"inline_keyboard":rows})
        if action=="offercancel":
            o=await self.db("cancel_offer",int(parts[2]),uid)
            await self.sync_offer(o)
            return await self.say(uid,f"Offer #{o.id} отменён.")
        if action=="logs":
            page=max(0,int(parts[2]))
            total,items=await self.db("event_log",page,10)
            lines=["🧾 <b>Offer и системные события</b>"]
            for e in items:
                lines.append(f"{rnd.expiry_string(e.created_at)} · <b>{rnd.h(e.event_type)}</b>\nactor={e.actor_id or '—'} target={e.target_id or '—'} offer={e.offer_id or '—'}")
            rows=[]
            if page:rows.append(kb.btn("◀️",f"admin:logs:{page-1}"))
            if (page+1)*10<total:rows.append(kb.btn("▶️",f"admin:logs:{page+1}"))
            return await self.say(uid,"\n".join(lines),kb.inline(rows,[kb.btn("↩️ Назад","admin:panel")]) if rows else kb.inline([kb.btn("↩️ Назад","admin:panel")]))
        if action=="audit":
            page=max(0,int(parts[2]))
            total,items=await self.db("admin_log",page,10)
            lines=["📑 <b>Admin Audit</b>"]
            for e in items:
                lines.append(f"{rnd.expiry_string(e.created_at)} · {rnd.h(e.action)} · <code>{e.actor_id}</code> → <code>{e.target_id or '—'}</code>")
            rows=[]
            if page:rows.append(kb.btn("◀️",f"admin:audit:{page-1}"))
            if (page+1)*10<total:rows.append(kb.btn("▶️",f"admin:audit:{page+1}"))
            return await self.say(uid,"\n".join(lines),kb.inline(rows,[kb.btn("↩️ Назад","admin:panel")]) if rows else kb.inline([kb.btn("↩️ Назад","admin:panel")]))
        raise DomainError("Неизвестное меню администратора")

    async def show_user(self,actor:int,uid:int):
        r=await self.db("user_details",uid)
        if not r:raise DomainError("Пользователь не найден")
        u,connections,offers,sent,actions=r
        txt=(f"👤 <b>Пользователь {uid}</b>\nUsername: {rnd.h(u.username or '—')}\n"
             f"Role: <b>{rnd.h(u.role)}</b>\nAllowed: {u.allowed}\nBlocked: {u.blocked}\n"
             f"Зарегистрирован: {rnd.expiry_string(u.created_at)}\n"
             f"Последняя активность: {rnd.expiry_string(u.last_activity_at) if u.last_activity_at else '—'}\n"
             f"Business Connections: {connections}\nOffers: {offers}\nSent: {sent}\nEvents: {actions}")
        return await self.say(actor,txt,kb.user_actions(uid,u.role=="owner"))
