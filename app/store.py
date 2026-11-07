"""Atomic repositories and domain services. SQL transactions own every state change."""
from __future__ import annotations
from datetime import timedelta, datetime
import re
from collections import Counter
from sqlalchemy import select, func, or_, delete
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .db import Database
from .models import User, BusinessConnection, BusinessChat, Offer, OfferEvent, Recipient, AdminAudit, UserFlow, ProcessedUpdate, CallbackReceipt, AppSetting, InlineOffer, InlineMessageState
from .states import (utcnow, aware, assert_transition, ACTION_EVENT, OFFER_TRANSITIONS, validate_gift_url, parse_stars, parse_duration)


class DomainError(ValueError):
    pass


class Store:
    def __init__(self, db: Database, config: Settings):
        self.db, self.config = db, config

    @staticmethod
    def _event(s, name: str, actor_id=None, target_id=None, offer_id=None, connection=None, metadata=None):
        s.add(OfferEvent(event_type=name, actor_id=actor_id, target_id=target_id,
                         offer_id=offer_id, business_connection_id=connection, event_metadata=metadata or {}, created_at=utcnow()))

    def initialize_admins(self):
        with self.db.transaction() as s:
            for id_ in self.config.admin_id_set:
                u = s.get(User, id_) or User(telegram_id=id_, created_at=utcnow(), updated_at=utcnow())
                if u not in s:
                    s.add(u)
                u.role = "owner" if id_ in self.config.owner_id_set else "admin"
                u.allowed = True
                u.blocked = False

    def touch_user(self, sender: dict, started=False) -> User:
        uid = int(sender["id"])
        with self.db.transaction() as s:
            u = s.get(User, uid)
            is_new = u is None
            if u is None:
                u = User(telegram_id=uid, role="user", allowed=False, blocked=False)
                s.add(u)
            u.username = sender.get("username")
            u.first_name = sender.get("first_name")
            u.last_activity_at = utcnow()
            if started:
                self._event(s, "USER_STARTED_BOT", actor_id=uid, metadata={"new_user":is_new})
            s.flush()
            return u

    def user(self, uid: int) -> User | None:
        with self.db.transaction() as s:
            return s.get(User, uid)

    def can_create(self, uid: int) -> bool:
        u = self.user(uid)
        return bool(u and u.allowed and not u.blocked)

    def is_admin(self, uid: int) -> bool:
        u = self.user(uid)
        return bool(u and u.allowed and not u.blocked and u.role in {"admin", "owner"})

    def _require_admin(self, s, actor: int, owner_only: bool = False):
        a = s.get(User, actor)
        if a is None or a.blocked or not a.allowed or a.role not in ({"owner"} if owner_only else {"admin", "owner"}):
            raise DomainError("Недостаточно прав администратора")
        return a

    def set_user_access(self, actor: int, target: int, action: str):
        names = {"allow": "USER_ALLOWED", "revoke": "USER_ACCESS_REMOVED", "block": "USER_BLOCKED", "unblock": "USER_UNBLOCKED", "promote": "ADMIN_ADDED", "demote": "ADMIN_REMOVED"}
        if action not in names or target <= 0:
            raise DomainError("Недопустимое действие или Telegram ID")
        with self.db.transaction() as s:
            a = self._require_admin(s, actor, owner_only=action in {"promote", "demote"})
            u = s.get(User, target)
            if not u:
                u = User(telegram_id=target, role="user", allowed=False, blocked=False)
                s.add(u)
            if u.role == "owner" and action in {"revoke", "block", "demote"}:
                raise DomainError("Нельзя лишить владельца доступа или роли")
            if target in self.config.admin_id_set and action in {"revoke", "block", "demote"}:
                raise DomainError("Этот администратор закреплён ADMIN_IDS. Измените Railway Variables")
            if action == "allow": u.allowed = True
            elif action == "revoke": u.allowed = False
            elif action == "block": u.blocked = True
            elif action == "unblock": u.blocked = False
            elif action == "promote":
                u.role, u.allowed, u.blocked = "admin", True, False
            elif action == "demote": u.role = "user"
            s.add(AdminAudit(actor_id=actor, target_id=target, action=names[action], event_metadata={}, created_at=utcnow()))
            self._event(s, names[action], actor_id=actor, target_id=target)
            s.flush()
            return u

    def display_contact(self) -> tuple[str | None, str]:
        """This is a DEMO support contact, not an NFT transfer recipient."""
        with self.db.transaction() as s:
            setting = s.get(AppSetting, "demo_contact_username")
            if setting:
                return setting.value, "Админ-панель"
        return self.config.demo_contact_username, "Railway" if self.config.demo_contact_username else "Не указан"

    def set_display_contact(self, actor: int, username: str | None):
        """Admin-only, validated and audited. None resets to the Railway default."""
        if username is not None:
            username = username.strip().lstrip("@").lower()
            if not re.fullmatch(r"[a-z0-9_]{5,32}", username):
                raise DomainError("Username: 5–32 латинских букв, цифр или _")
        with self.db.transaction() as s:
            self._require_admin(s, actor)
            setting = s.get(AppSetting, "demo_contact_username")
            old = setting.value if setting else None
            if username is None:
                if setting:
                    s.delete(setting)
            else:
                if setting is None:
                    setting = AppSetting(key="demo_contact_username", value=username)
                    s.add(setting)
                else:
                    setting.value = username
                setting.updated_at = utcnow()
                setting.updated_by = actor
            s.add(AdminAudit(actor_id=actor, target_id=None, action="DEMO_CONTACT_UPDATED",
                             event_metadata={"previous": old, "current": username}, created_at=utcnow()))
            self._event(s, "DEMO_CONTACT_UPDATED", actor_id=actor,
                        metadata={"previous": old, "current": username})
        return self.display_contact()

    DEFAULT_FAQ = (
        "❔ Частые вопросы\n\n"
        "1. Почему не появляется карточка?\n"
        "Проверьте /test в личном чате бота. Для отправки в другой чат "
        "включите Guest Mode через Mini App @BotFather и отправьте "
        "@имя_бота с NFT-ссылкой, Stars и минутами в нужный чат.\n\n"
        "2. Почему бот не заменяет обычное сообщение?\n"
        "Обычные сообщения пользователя в чужих чатах бот не редактирует. "
        "В Telegram Business доступны лишь чаты и действия, разрешённые Telegram.\n\n"
        "3. Что означают Stars и кнопки?\n"
        "Это DEMO: оплата и передача NFT отсутствуют. Не отправляйте подарки или деньги для тестирования.\n\n"
        "4. Ошибка при отправке?\n"
        "Откройте /diag или передайте поддержке текст ошибки без токенов и паролей."
    )

    def display_faq(self) -> str:
        with self.db.transaction() as s:
            entry = s.get(AppSetting, "faq_text")
            return entry.value if entry else self.DEFAULT_FAQ

    def set_faq_text(self, actor: int, faq: str | None) -> str:
        """Admins can update the FAQ as plain text. None restores the default."""
        if faq is not None:
            faq = faq.strip()
            if not 30 <= len(faq) <= 3000:
                raise DomainError("FAQ: от 30 до 3000 символов")
        with self.db.transaction() as s:
            self._require_admin(s, actor)
            entry = s.get(AppSetting, "faq_text")
            if faq is None:
                if entry:
                    s.delete(entry)
            else:
                if entry is None:
                    s.add(AppSetting(key="faq_text", value=faq, updated_by=actor, updated_at=utcnow()))
                else:
                    entry.value, entry.updated_by, entry.updated_at = faq, actor, utcnow()
            s.add(AdminAudit(actor_id=actor, target_id=None, action="FAQ_UPDATED",
                             event_metadata={"mode": "reset" if faq is None else "updated"},
                             created_at=utcnow()))
            self._event(s, "FAQ_UPDATED", actor_id=actor)
        return self.display_faq()

    def get_users(self, page=0, limit=8):
        with self.db.transaction() as s:
            total = s.scalar(select(func.count()).select_from(User)) or 0
            items = s.scalars(select(User).order_by(User.created_at.desc(), User.telegram_id).limit(limit).offset(max(0, page)*limit)).all()
            return total, items

    def user_details(self, uid: int):
        with self.db.transaction() as s:
            u = s.get(User, uid)
            if not u: return None
            return (u, s.scalar(select(func.count()).select_from(BusinessConnection).where(BusinessConnection.owner_user_id == uid)) or 0,
                    s.scalar(select(func.count()).select_from(Offer).where(Offer.creator_id == uid)) or 0,
                    s.scalar(select(func.count()).select_from(Offer).where(Offer.creator_id == uid, Offer.sent_at.is_not(None))) or 0,
                    s.scalar(select(func.count()).select_from(OfferEvent).where(OfferEvent.actor_id == uid)) or 0)

    def connection_update(self, bc: dict):
        conn_id = bc.get("id")
        owner = bc.get("user") or {}
        if not conn_id or not owner.get("id"): return
        with self.db.transaction() as s:
            b = s.scalar(select(BusinessConnection).where(BusinessConnection.business_connection_id == conn_id))
            fresh = b is None
            old = (b.active, b.permissions, b.owner_user_id, b.owner_username) if b else None
            if b is None:
                established=(datetime.fromtimestamp(int(bc["date"]),tz=utcnow().tzinfo)
                             if bc.get("date") else utcnow())
                b = BusinessConnection(business_connection_id=conn_id, owner_user_id=int(owner["id"]), connected_at=established)
                s.add(b)
            b.owner_user_id = int(owner["id"])
            b.owner_username = owner.get("username")
            b.active = bool(bc.get("is_enabled", False))
            b.permissions = bc.get("rights") or {}
            b.updated_at = utcnow()
            b.last_activity_at = utcnow()
            current=(b.active,b.permissions,b.owner_user_id,b.owner_username)
            if fresh or old != current:
                event = "BUSINESS_DISCONNECTED" if not b.active else "BUSINESS_CONNECTED" if fresh or not old[0] else "BUSINESS_UPDATED"
                self._event(s,event,actor_id=b.owner_user_id,connection=conn_id)

    def business_incoming(self, msg: dict):
        conn_id = msg.get("business_connection_id")
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        if not conn_id or chat.get("type") != "private" or not sender.get("id"):
            return False
        with self.db.transaction() as s:
            b = s.scalar(select(BusinessConnection).where(BusinessConnection.business_connection_id == conn_id))
            if b is None or not b.active:
                return False
            b.last_activity_at = utcnow()
            if int(sender["id"]) == b.owner_user_id:
                return False
            if int(sender["id"]) != int(chat["id"]):
                return False
            rec = s.scalar(select(BusinessChat).where(BusinessChat.business_connection_id == conn_id, BusinessChat.chat_id == int(chat["id"])))
            if rec is None:
                rec = BusinessChat(business_connection_id=conn_id, chat_id=int(chat["id"]), active=True)
                s.add(rec)
            rec.user_id = int(sender["id"])
            rec.username = sender.get("username")
            rec.first_name = sender.get("first_name")
            rec.last_activity_at = utcnow()
            # Telegram may redeliver old updates after restart. Do not extend reply window using processing time.
            received_at = datetime.fromtimestamp(int(msg.get("date", 0)), tz=utcnow().tzinfo)
            if rec.last_incoming_at is None or aware(rec.last_incoming_at) < received_at:
                rec.last_incoming_at = received_at
            rec.active = True
            rp = s.scalar(select(Recipient).where(Recipient.business_connection_id == conn_id, Recipient.telegram_chat_id == rec.chat_id))
            if rp is None:
                rp = Recipient(business_connection_id=conn_id, telegram_chat_id=rec.chat_id, created_at=utcnow())
                s.add(rp)
            rp.telegram_user_id = rec.user_id
            rp.username = rec.username
            rp.label = rec.first_name
            rp.active = True
        return True

    def business_deleted(self, message: dict):
        conn_id = message.get("business_connection_id")
        ids = message.get("message_ids") or []
        if not conn_id or not ids: return
        with self.db.transaction() as s:
            offers = s.scalars(select(Offer).where(Offer.business_connection_id == conn_id,
                                                   Offer.recipient_chat_id == (message.get("chat") or {}).get("id"),
                                                   Offer.telegram_message_id.in_(ids))).all()
            for o in offers:
                o.delivery_status = "deleted"
                o.sync_needed = False
                self._event(s, "OFFER_MESSAGE_DELETED", offer_id=o.id, connection=conn_id)

    def connections(self, requester: int):
        with self.db.transaction() as s:
            a = s.get(User, requester)
            if not a or a.blocked or not a.allowed:
                return []
            q = select(BusinessConnection).order_by(BusinessConnection.updated_at.desc())
            if a.role not in {"admin", "owner"}:
                q = q.where(BusinessConnection.owner_user_id == requester)
            return s.scalars(q).all()

    def admins(self, page=0, limit=8):
        with self.db.transaction() as s:
            q=select(User).where(User.role.in_(["admin","owner"]))
            total=s.scalar(select(func.count()).select_from(q.subquery())) or 0
            rows=s.scalars(q.order_by(User.role.desc(),User.telegram_id).limit(limit).offset(max(0,page)*limit)).all()
            return total,rows

    def _eligible_chats(self, s, actor: int, only_recent=False):
        a = s.get(User, actor)
        if not a or a.blocked or not a.allowed: return []
        stmt = (select(BusinessChat, BusinessConnection)
                .join(BusinessConnection, BusinessConnection.business_connection_id == BusinessChat.business_connection_id)
                .where(BusinessChat.active.is_(True), BusinessConnection.active.is_(True))
                .order_by(BusinessChat.last_incoming_at.desc()))
        if a.role not in {"admin", "owner"}:
            stmt = stmt.where(BusinessConnection.owner_user_id == actor)
        rows = s.execute(stmt).all()
        if only_recent:
            rows = [(ch, c) for ch, c in rows if self._can_send(ch, c)]
        return rows

    @staticmethod
    def _can_send(ch: BusinessChat, connection: BusinessConnection) -> bool:
        return bool(connection.active and connection.permissions.get("can_reply") and
                    ch.active and ch.last_incoming_at and
                    aware(ch.last_incoming_at) > utcnow() - timedelta(hours=24))

    def known_chats(self, actor: int, page=0, limit=8):
        with self.db.transaction() as s:
            rows = self._eligible_chats(s, actor)
            return len(rows), [(ch, conn, self._can_send(ch, conn)) for ch, conn in rows[max(0,page)*limit:(max(0,page)+1)*limit]]

    def _resolve_chat(self, s, actor: int, chosen_chat_pk: int | None = None):
        rows = self._eligible_chats(s, actor, only_recent=False)
        # Explicit Railway Chat ID has precedence over all local selections.
        if self.config.target_chat_id is not None:
            matched = [(c, b) for c, b in rows if c.chat_id == self.config.target_chat_id]
            source = "Railway TARGET_CHAT_ID"
        elif chosen_chat_pk is not None:
            matched = [(c, b) for c, b in rows if c.id == chosen_chat_pk]
            source = "Выбранный Business Chat"
        elif self.config.target_user_id is not None:
            matched = [(c, b) for c, b in rows if c.user_id == self.config.target_user_id]
            source = "Railway TARGET_USER_ID"
        elif self.config.target_username:
            matched = [(c, b) for c, b in rows if c.username and c.username.lower() == self.config.target_username]
            source = "Railway TARGET_USERNAME (обнаруженный чат)"
        else:
            recent = [(c,b) for c,b in rows if self._can_send(c,b)]
            matched = recent if len(recent) == 1 else []
            source = "Единственный доступный Business Chat" if matched else "Требуется явный выбор"
        if len(matched) == 0:
            raise DomainError(f"Target не найден: {source}. Получатель должен написать Business-аккаунту в течение последних 24 часов")
        if len(matched) > 1:
            raise DomainError("Target неоднозначен: найдены несколько Business Connections. Выберите конкретный чат")
        ch, conn = matched[0]
        if not self._can_send(ch, conn):
            raise DomainError("Target недоступен: требуется активный Business Connection, право can_reply и входящее сообщение за последние 24 часа")
        return ch, conn, source

    def resolve_target(self, actor: int, chosen_chat_pk: int | None = None) -> dict:
        with self.db.transaction() as s:
            c, b, source = self._resolve_chat(s, actor, chosen_chat_pk)
            return {"chat_pk": c.id, "chat_id": c.chat_id, "user_id": c.user_id or c.chat_id,
                    "username": c.username, "name": c.first_name, "connection_id": b.business_connection_id,
                    "owner_user_id": b.owner_user_id, "source": source, "last_incoming_at": c.last_incoming_at}

    def describe_target(self, actor: int) -> dict:
        try:
            v = self.resolve_target(actor)
            v["available"] = True
            return v
        except DomainError as e:
            return {"available": False, "error": str(e), "source": "Railway" if self.config.target_chat_id or self.config.target_user_id or self.config.target_username else "Нет автоматического Target"}

    def save_flow(self, uid: int, state: str, payload: dict | None = None):
        with self.db.transaction() as s:
            f = s.get(UserFlow, uid)
            if f is None:
                f = UserFlow(user_id=uid, state=state, payload={})
                s.add(f)
            f.state, f.payload, f.updated_at = state, payload or {}, utcnow()

    def flow(self, uid: int):
        with self.db.transaction() as s:
            f = s.get(UserFlow, uid)
            return (f.state, dict(f.payload)) if f else (None, {})

    def clear_flow(self, uid: int):
        with self.db.transaction() as s:
            f = s.get(UserFlow, uid)
            if f: s.delete(f)

    def register_update(self, update_id: int) -> bool:
        with self.db.transaction() as s:
            if s.get(ProcessedUpdate, update_id): return False
            s.add(ProcessedUpdate(update_id=update_id, created_at=utcnow()))
            return True

    def forget_update(self, update_id: int):
        with self.db.transaction() as s:
            s.execute(delete(ProcessedUpdate).where(ProcessedUpdate.update_id == update_id))

    def register_callback(self, callback_id: str) -> bool:
        with self.db.transaction() as s:
            if s.get(CallbackReceipt, callback_id): return False
            s.add(CallbackReceipt(callback_id=callback_id, created_at=utcnow()))
            return True

    def create_offer(self, creator: int, payload: dict) -> Offer:
        with self.db.transaction() as s:
            actor = s.get(User, creator)
            if not actor or not actor.allowed or actor.blocked:
                raise DomainError("Нет доступа к созданию предложений")
            chosen = payload.get("target_chat_pk")
            ch, conn, _ = self._resolve_chat(s, creator, chosen)
            from .states import parse_duration
            expiry = parse_duration(str(payload.get("duration", self.config.default_expiration)))
            stars = parse_stars(str(payload.get("stars")))
            gift_url = validate_gift_url(payload.get("gift_url") or "")
            gift_name = str(payload.get("gift_name") or "").strip()
            if not 1 <= len(gift_name) <= 150:
                raise DomainError("Название Gift должно содержать от 1 до 150 символов")
            o = Offer(creator_id=creator, recipient_user_id=ch.user_id or ch.chat_id,
                      recipient_chat_id=ch.chat_id, business_connection_id=conn.business_connection_id,
                      gift_url=gift_url, gift_name=gift_name,
                      gift_image_file_id=payload.get("image_file_id"), media_kind=payload.get("media_kind", "photo"),
                      stars_amount=stars, expires_at=utcnow()+timedelta(minutes=expiry),
                      status="draft", delivery_status="sending", sending_started_at=utcnow(),
                      created_at=utcnow(), updated_at=utcnow(), sync_needed=False, version=0)
            s.add(o)
            s.flush()
            self._event(s, "OFFER_CREATED", actor_id=creator, target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id, metadata={"demo": True})
            return o

    def can_issue_business_command(self, actor: int, connection_id: str, chat_id: int) -> bool:
        with self.db.transaction() as s:
            a = s.get(User, actor)
            bc = s.scalar(select(BusinessConnection).where(BusinessConnection.business_connection_id == connection_id))
            ch = s.scalar(select(BusinessChat).where(BusinessChat.business_connection_id == connection_id,
                                                    BusinessChat.chat_id == chat_id))
            return bool(a and a.allowed and not a.blocked and bc and bc.active and
                        bc.owner_user_id == actor and ch and self._can_send(ch, bc))

    def can_delete_business_source(self, owner_id: int, connection_id: str) -> bool:
        with self.db.transaction() as s:
            bc = s.scalar(select(BusinessConnection).where(
                BusinessConnection.business_connection_id == connection_id))
            return bool(bc and bc.active and bc.owner_user_id == owner_id and
                        bc.permissions.get("can_delete_all_messages"))

    def business_offer_by_source(self, connection_id: str, chat_id: int, message_id: int):
        with self.db.transaction() as s:
            return s.scalar(select(Offer).where(Offer.business_connection_id == connection_id,
                                                Offer.recipient_chat_id == chat_id,
                                                Offer.source_message_id == message_id))

    def create_business_chat_offer(self, creator: int, connection_id: str, chat_id: int,
                                   source_message_id: int, payload: dict) -> Offer:
        """Atomically create a demo offer for THIS Business chat, not Railway TARGET.

        Only the connected Business owner with whitelist access may issue this
        command. The exact chat must have received a client message in the last
        24h, and Telegram must have granted can_reply.
        """
        with self.db.transaction() as s:
            actor = s.get(User, creator)
            bc = s.scalar(select(BusinessConnection).where(
                BusinessConnection.business_connection_id == connection_id))
            ch = s.scalar(select(BusinessChat).where(
                BusinessChat.business_connection_id == connection_id,
                BusinessChat.chat_id == chat_id))
            if not actor or not actor.allowed or actor.blocked:
                raise DomainError("Создание доступно только разрешённым пользователям")
            if not bc or not bc.active or bc.owner_user_id != creator:
                raise DomainError("Только владелец Business Connection может отправлять офер из переписки")
            if not ch or not self._can_send(ch, bc):
                raise DomainError("Недоступен этот Business Chat: нужен can_reply и входящее сообщение за последние 24 часа")
            existing = s.scalar(select(Offer).where(
                Offer.business_connection_id == connection_id,
                Offer.recipient_chat_id == chat_id,
                Offer.source_message_id == source_message_id))
            if existing:
                return existing
            expiry = parse_duration(str(payload["duration"]))
            stars = parse_stars(str(payload["stars"]))
            gift_url = validate_gift_url(payload["gift_url"])
            gift_name = str(payload.get("gift_name") or "").strip()
            if not 1 <= len(gift_name) <= 150:
                raise DomainError("Неправильное название NFT")
            now = utcnow()
            o = Offer(creator_id=creator, recipient_user_id=ch.user_id or ch.chat_id,
                      recipient_chat_id=chat_id, business_connection_id=connection_id,
                      source_message_id=source_message_id, gift_url=gift_url,
                      gift_name=gift_name,
                      gift_image_file_id=payload.get("image_file_id"), media_kind=payload.get("media_kind", "photo"),
                      stars_amount=stars, created_at=now, expires_at=now+timedelta(minutes=expiry),
                      status="draft", delivery_status="sending", sending_started_at=now,
                      updated_at=now, sync_needed=False, version=0)
            s.add(o)
            s.flush()
            self._event(s, "OFFER_CREATED", actor_id=creator, target_id=o.recipient_user_id,
                        offer_id=o.id, connection=connection_id,
                        metadata={"demo": True, "via": "business_chat", "source_message_id": source_message_id})
            return o

    def refresh_send_authorization(self, offer_id: int):
        with self.db.transaction() as s:
            o = s.get(Offer, offer_id)
            if not o or o.status != "draft" or o.delivery_status != "sending":
                raise DomainError("Offer больше недоступен для отправки")
            self._require_or_creator(s, o.creator_id, o.creator_id)
            ch = s.scalar(select(BusinessChat).where(BusinessChat.business_connection_id == o.business_connection_id,
                                                    BusinessChat.chat_id == o.recipient_chat_id))
            bc = s.scalar(select(BusinessConnection).where(BusinessConnection.business_connection_id == o.business_connection_id))
            if not ch or not bc or not self._can_send(ch, bc):
                raise DomainError("Business Chat недоступен: право can_reply или 24-часовое окно истекло")
            return o

    def mark_sent(self, offer_id: int, message_id: int, photo_file_id: str | None = None):
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one()
            if o.delivery_status != "sending" or o.status != "draft":
                raise DomainError("Предложение имеет непредвиденное состояние отправки")
            o.status, o.delivery_status, o.telegram_message_id, o.sent_at = "active", "sent", message_id, utcnow()
            if photo_file_id:
                o.gift_image_file_id = photo_file_id
            o.version += 1
            self._event(s, "OFFER_SENT", actor_id=o.creator_id, target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id)
            return o

    def mark_failed(self, offer_id: int, error: str):
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one()
            if o.delivery_status == "sending":
                o.delivery_status = "failed"
                self._event(s, "OFFER_SEND_FAILED", actor_id=o.creator_id, target_id=o.recipient_user_id,
                            offer_id=o.id, connection=o.business_connection_id, metadata={"reason": error[:300]})

    def mark_unknown(self, offer_id: int, reason: str):
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one()
            if o.delivery_status == "sending":
                o.delivery_status = "unknown"
                self._event(s, "OFFER_DELIVERY_UNCERTAIN", actor_id=o.creator_id, offer_id=o.id,
                            connection=o.business_connection_id, metadata={"reason": reason[:300]})

    def retry_send(self, offer_id: int, creator: int):
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one_or_none()
            if not o or o.creator_id != creator or o.status != "draft" or o.delivery_status != "failed":
                raise DomainError("Повторная отправка невозможна")
            self._require_or_creator(s, creator, o.creator_id)
            ch = s.scalar(select(BusinessChat).where(BusinessChat.business_connection_id == o.business_connection_id, BusinessChat.chat_id == o.recipient_chat_id))
            bc = s.scalar(select(BusinessConnection).where(BusinessConnection.business_connection_id == o.business_connection_id))
            if not ch or not bc or not self._can_send(ch,bc):
                raise DomainError("Target стал недоступен")
            duration = max(1, int((aware(o.expires_at) - aware(o.created_at)).total_seconds() // 60))
            o.expires_at = utcnow() + timedelta(minutes=duration)
            o.delivery_status, o.sending_started_at = "sending", utcnow()
            self._event(s, "OFFER_SEND_RETRIED", actor_id=creator, offer_id=o.id)
            return o

    def offer(self, offer_id: int):
        with self.db.transaction() as s:
            return s.get(Offer, offer_id)

    def offers_by_creator(self, uid: int, page=0, limit=8, all_offers=False):
        with self.db.transaction() as s:
            q = select(Offer)
            if not all_offers: q = q.where(Offer.creator_id == uid)
            total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
            return total, s.scalars(q.order_by(Offer.created_at.desc(), Offer.id.desc()).limit(limit).offset(max(0,page)*limit)).all()

    def offer_transition(self, offer_id: int, actor_id: int, action: str) -> tuple[Offer, bool]:
        """Atomic; returns (offer, expired_during_click)."""
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one_or_none()
            if not o: raise DomainError("Offer не найден")
            if o.recipient_user_id != actor_id:
                raise DomainError("Это предложение адресовано другому пользователю")
            user = s.get(User, actor_id)
            if user and user.blocked:
                raise DomainError("Для этого пользователя действия заблокированы")
            if o.delivery_status != "sent":
                raise DomainError("Сообщение не находится в доступном состоянии")
            if o.status == "active" and aware(o.expires_at) <= utcnow():
                o.status, o.version, o.sync_needed = "expired", o.version + 1, True
                self._event(s, "OFFER_EXPIRED", target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id)
                return o, True
            try:
                status = assert_transition(o.status, action, o.expires_at)
            except ValueError as e:
                raise DomainError(str(e)) from e
            o.status, o.version, o.sync_needed = status, o.version+1, True
            field = {"accept": "accepted_at", "decline": "declined_at", "transfer": "transfer_requested_at"}[action]
            setattr(o, field, utcnow())
            self._event(s, ACTION_EVENT[action], actor_id=actor_id, target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id, metadata={"demo":True})
            return o, False

    def open_instructions(self, offer_id: int, actor: int) -> Offer:
        with self.db.transaction() as s:
            o = s.get(Offer, offer_id)
            if not o or o.recipient_user_id != actor:
                raise DomainError("Нет доступа к инструкции")
            if o.status != "accepted" or o.delivery_status != "sent":
                raise DomainError("Инструкция доступна только для принятого DEMO Offer")
            u = s.get(User, actor)
            if u and u.blocked:
                raise DomainError("Действие заблокировано")
            self._event(s, "INSTRUCTION_OPENED", actor_id=actor, target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id)
            return o

    def cancel_offer(self, offer_id: int, actor_id: int) -> Offer:
        with self.db.transaction() as s:
            o = s.execute(select(Offer).where(Offer.id == offer_id).with_for_update()).scalar_one_or_none()
            if not o: raise DomainError("Offer не найден")
            a = self._require_or_creator(s, actor_id, o.creator_id)
            if not (o.status == "active" or (o.status == "draft" and o.delivery_status in {"pending", "failed"})):
                raise DomainError("Это предложение нельзя отменить (возможна незавершённая доставка)")
            o.status, o.cancelled_at, o.sync_needed = "cancelled", utcnow(), o.telegram_message_id is not None
            o.version += 1
            self._event(s, "OFFER_CANCELLED", actor_id=actor_id, target_id=o.recipient_user_id, offer_id=o.id, connection=o.business_connection_id)
            return o

    @staticmethod
    def _require_or_creator(s, actor_id: int, creator_id: int):
        a = s.get(User, actor_id)
        if not a or a.blocked or not a.allowed or (actor_id != creator_id and a.role not in {"owner", "admin"}):
            raise DomainError("Нет прав на управление Offer")
        return a

    def due_offers(self, limit=50):
        with self.db.transaction() as s:
            rows = s.scalars(select(Offer).where(Offer.status == "active", Offer.expires_at <= utcnow())
                             .order_by(Offer.expires_at).limit(limit).with_for_update(skip_locked=True)).all()
            ids=[]
            for o in rows:
                o.status, o.sync_needed, o.version = "expired", True, o.version + 1
                self._event(s, "OFFER_EXPIRED", offer_id=o.id, target_id=o.recipient_user_id, connection=o.business_connection_id)
                ids.append(o.id)
            return ids

    def pending_sync(self, limit=40):
        with self.db.transaction() as s:
            return s.scalars(select(Offer).where(Offer.sync_needed.is_(True), Offer.telegram_message_id.is_not(None))
                             .order_by(Offer.updated_at).limit(limit)).all()

    def mark_synced(self, offer_id: int, expected_version: int):
        with self.db.transaction() as s:
            o = s.get(Offer, offer_id)
            if o and o.version == expected_version: o.sync_needed = False

    def permanent_sync_error(self, offer_id: int, reason: str):
        with self.db.transaction() as s:
            o = s.get(Offer, offer_id)
            if o:
                o.sync_needed = False
                self._event(s, "OFFER_MESSAGE_SYNC_FAILED", offer_id=o.id, connection=o.business_connection_id, metadata={"reason":reason[:300]})

    def reconcile_sends(self, minutes=2):
        with self.db.transaction() as s:
            rows = s.scalars(select(Offer).where(Offer.delivery_status == "sending", Offer.sending_started_at < utcnow()-timedelta(minutes=minutes))
                             .with_for_update(skip_locked=True)).all()
            for o in rows:
                # Telegram API request might have succeeded before crash. Never automatically duplicate it.
                o.delivery_status = "unknown"
                self._event(s, "OFFER_DELIVERY_UNCERTAIN", offer_id=o.id, connection=o.business_connection_id)
            return len(rows)

    def personal_stats(self, uid: int):
        with self.db.transaction() as s:
            total=s.scalar(select(func.count()).select_from(Offer).where(Offer.creator_id == uid)) or 0
            sent=s.scalar(select(func.count()).select_from(Offer).where(Offer.creator_id == uid,Offer.sent_at.is_not(None))) or 0
            grouped=s.execute(select(Offer.status,func.count()).where(Offer.creator_id == uid).group_by(Offer.status)).all()
            return {"total":total,"sent":sent,"statuses":dict(grouped)}

    def stats(self):
        with self.db.transaction() as s:
            counts={}
            for k,q in {
                "users":select(func.count()).select_from(User),
                "allowed":select(func.count()).select_from(User).where(User.allowed.is_(True)),
                "blocked":select(func.count()).select_from(User).where(User.blocked.is_(True)),
                "admins":select(func.count()).select_from(User).where(User.role.in_(["admin","owner"])),
                "connections":select(func.count()).select_from(BusinessConnection),
                "active_connections":select(func.count()).select_from(BusinessConnection).where(BusinessConnection.active.is_(True)),
                "offers_created":select(func.count()).select_from(Offer),
                "offers_sent":select(func.count()).select_from(Offer).where(Offer.sent_at.is_not(None)),
                "instructions":select(func.count()).select_from(OfferEvent).where(OfferEvent.event_type=="INSTRUCTION_OPENED"),
                "today":select(func.count()).select_from(OfferEvent).where(OfferEvent.created_at >= utcnow().replace(hour=0,minute=0,second=0,microsecond=0)),
                "week":select(func.count()).select_from(OfferEvent).where(OfferEvent.created_at >= utcnow()-timedelta(days=7)),
                "all_time":select(func.count()).select_from(OfferEvent),
            }.items():counts[k] = s.scalar(q) or 0
            statuses=s.execute(select(Offer.status,func.count()).group_by(Offer.status)).all()
            counts.update({name:num for name,num in statuses})
            return counts

    def event_log(self, page=0, limit=10):
        with self.db.transaction() as s:
            q=select(OfferEvent)
            total=s.scalar(select(func.count()).select_from(OfferEvent)) or 0
            return total,s.scalars(q.order_by(OfferEvent.id.desc()).limit(limit).offset(page*limit)).all()

    def admin_log(self, page=0, limit=10):
        with self.db.transaction() as s:
            total=s.scalar(select(func.count()).select_from(AdminAudit)) or 0
            rows=s.scalars(select(AdminAudit).order_by(AdminAudit.id.desc()).limit(limit).offset(page*limit)).all()
            return total, rows

    def prune_receipts(self, days=30):
        threshold=utcnow()-timedelta(days=days)
        with self.db.transaction() as s:
            s.execute(delete(ProcessedUpdate).where(ProcessedUpdate.created_at < threshold))
            s.execute(delete(CallbackReceipt).where(CallbackReceipt.created_at < threshold))

    def create_inline_offer(self, creator: int, offer_data: dict, guest_query_id: str | None = None):
        """Create a shareable DEMO template for a valid, authorized inline query."""
        with self.db.transaction() as s:
            actor = s.get(User, creator)
            if not actor or not actor.allowed or actor.blocked:
                raise DomainError("Нет доступа к созданию inline-оферов")
            if guest_query_id is not None:
                if not guest_query_id or len(guest_query_id) > 512:
                    raise DomainError("Некорректный гостевой запрос")
                if s.scalar(select(InlineOffer.id).where(InlineOffer.guest_query_id == guest_query_id)):
                    return None  # already claimed, including an ambiguous network result
            obj = InlineOffer(
                creator_id=creator,
                guest_query_id=guest_query_id,
                gift_url=validate_gift_url(offer_data["gift_url"]),
                gift_name=str(offer_data["gift_name"])[:150],
                stars_amount=parse_stars(str(offer_data["stars"])),
                expires_at=utcnow()+timedelta(minutes=parse_duration(str(offer_data["duration"]))),
                created_at=utcnow())
            s.add(obj)
            s.flush()
            return obj

    def bind_guest_message(self, offer_id: int, message_id: str):
        """Bind the answerGuestQuery result before accepting any unsigned callback."""
        if not isinstance(message_id, str) or not message_id or len(message_id) > 512:
            raise DomainError("Некорректное гостевое сообщение")
        with self.db.transaction() as s:
            offer = s.scalar(select(InlineOffer).where(InlineOffer.id == offer_id).with_for_update())
            if offer is None or not offer.guest_query_id:
                raise DomainError("Гостевой офер не найден")
            if offer.guest_inline_message_id not in {None, message_id}:
                raise DomainError("Несовпадение гостевого сообщения")
            offer.guest_inline_message_id = message_id

    def inline_action(self, offer_id: int, message_id: str, action: str,
                      actor_id: int | None = None, guest: bool = False,
                      guest_token: str | None = None):
        """Apply a DEMO status transition to one chosen inline message atomically."""
        if not isinstance(message_id, str) or not message_id or len(message_id) > 512:
            raise DomainError("Некорректное inline-сообщение")
        if action not in {"accept", "decline", "transfer", "instructions"}:
            raise DomainError("Неизвестная кнопка")
        with self.db.transaction() as s:
            # Lock the template as well: the first per-message row doesn't exist
            # yet, so locking only that row cannot serialize concurrent clicks.
            offer = s.scalar(select(InlineOffer).where(InlineOffer.id == offer_id).with_for_update())
            if not offer:
                raise DomainError("Тестовый офер не найден")
            if actor_id is not None:
                actor = s.get(User, actor_id)
                if actor and actor.blocked:
                    raise DomainError("Доступ заблокирован")
                if actor_id == offer.creator_id and action in {"accept", "decline"}:
                    raise DomainError("Офер предназначен собеседнику. Для своей проверки используйте /test")
            if offer.guest_query_id:
                if not guest:
                    raise DomainError("Нужна оригинальная гостевая кнопка")
                if guest_token is not None:
                    import hmac
                    from .guest_offers import guest_callback_token
                    expected = guest_callback_token(self.config.bot_token, offer.id, offer.guest_query_id)
                    if not hmac.compare_digest(expected, guest_token):
                        raise DomainError("Неправильная гостевая кнопка")
                if offer.guest_inline_message_id is None:
                    if guest_token is None:
                        raise DomainError("Доставка гостевого сообщения не подтверждена")
                    # A signed callback is proof that Telegram delivered the
                    # reply despite a lost answerGuestQuery HTTP response.
                    offer.guest_inline_message_id = message_id
                elif offer.guest_inline_message_id != message_id:
                    raise DomainError("Несовпадение гостевого сообщения")
            row = s.execute(select(InlineMessageState).where(
                InlineMessageState.inline_message_id == message_id).with_for_update()).scalar_one_or_none()
            if row is not None and row.inline_offer_id != offer_id:
                raise DomainError("Несовпадение inline-сообщения")
            if row is None:
                row = InlineMessageState(inline_message_id=message_id,
                                         inline_offer_id=offer_id, status="active",updated_at=utcnow())
                s.add(row)
            current = row.status
            if current == "expired":
                return offer, current  # allow repair after a failed Telegram edit
            if current == "active" and aware(offer.expires_at) <= utcnow():
                row.status = "expired"
            elif action != "instructions":
                if action == "transfer" and current == "accepted":
                    row.status = "transfer_requested"
                elif action in {"accept", "decline"} and current == "active":
                    row.status = "accepted" if action == "accept" else "declined"
                elif (action == "accept" and current == "accepted") or (action == "decline" and current == "declined") or (action == "transfer" and current == "transfer_requested"):
                    pass  # safe retry if Telegram edit failed
                else:
                    raise DomainError("Действие уже недоступно")
            row.updated_at = utcnow()
            return offer, row.status

    def prune_inline(self, days: int = 14):
        """Discard expired inline templates only after a generous editing window."""
        limit = utcnow() - timedelta(days=days)
        with self.db.transaction() as s:
            ids = select(InlineOffer.id).where(InlineOffer.expires_at < limit)
            s.execute(delete(InlineMessageState).where(InlineMessageState.inline_offer_id.in_(ids)))
            s.execute(delete(InlineOffer).where(InlineOffer.expires_at < limit))


    def diagnostics(self, uid: int) -> dict:
        """Local connection/send readiness for owners and admins only."""
        with self.db.transaction() as s:
            self._require_admin(s,uid)
            chats=self._eligible_chats(s,uid)
            connections={bc.business_connection_id: bc for _,bc in chats}
            return {"known_chats":len(chats),
                    "eligible_chats":sum(self._can_send(c,bc) for c,bc in chats),
                    "active_connections_in_known_chats":len(connections),
                    "with_delete_right":sum(bool(bc.permissions.get("can_delete_all_messages")) for bc in connections.values())}
