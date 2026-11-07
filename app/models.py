"""SQLAlchemy schema; events are append-only."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessConnection(Base):
    __tablename__ = "business_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_username: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessChat(Base):
    __tablename__ = "business_chats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), ForeignKey("business_connections.business_connection_id"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(200))
    last_incoming_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("business_connection_id", "chat_id", name="uq_business_chat"), Index("ix_business_chat_user", "user_id"))


class Recipient(Base):
    __tablename__ = "recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(100))
    business_connection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint("business_connection_id", "telegram_chat_id", name="uq_recipient_chat"),)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    recipient_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recipient_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    business_connection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)  # optional original Business command
    gift_url: Mapped[str] = mapped_column(String(400), nullable=False)
    gift_name: Mapped[str] = mapped_column(String(150), nullable=False)
    gift_image_file_id: Mapped[str | None] = mapped_column(String(300))
    media_kind: Mapped[str] = mapped_column(String(20), default="photo", nullable=False)
    stars_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transfer_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sending_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_needed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    __table_args__ = (CheckConstraint("stars_amount >= 1 AND stars_amount <= 1000000000000", name="ck_stars_range"), Index("ix_offers_due", "status", "expires_at"), Index("ix_offers_creator", "creator_id"), UniqueConstraint("business_connection_id", "recipient_chat_id", "source_message_id", name="uq_offer_business_command"))


class OfferEvent(Base):
    __tablename__ = "offer_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    offer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("offers.id"))
    business_connection_id: Mapped[str | None] = mapped_column(String(255))
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (Index("ix_offer_events_time", "created_at"), Index("ix_offer_events_offer", "offer_id"))


class AdminAudit(Base):
    __tablename__ = "admin_audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class UserFlow(Base):
    __tablename__ = "user_flows"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class CallbackReceipt(Base):
    __tablename__ = "callback_receipts"
    callback_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class AppSetting(Base):
    """Persisted non-secret admin-controlled display settings."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class InlineOffer(Base):
    """An inline DEMO offer template, shared only by the sender's selections."""
    __tablename__ = "inline_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gift_url: Mapped[str] = mapped_column(String(400), nullable=False)
    gift_name: Mapped[str] = mapped_column(String(150), nullable=False)
    stars_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    guest_query_id: Mapped[str | None] = mapped_column(String(512))
    guest_inline_message_id: Mapped[str | None] = mapped_column(String(512))
    __table_args__ = (Index("ix_inline_offers_expiry", "expires_at"),
                      Index("ix_inline_offers_guest_query", "guest_query_id", unique=True),
                      Index("ix_inline_offers_guest_message", "guest_inline_message_id", unique=True))


class InlineMessageState(Base):
    """Each selected inline message has its own status, even when a result is re-used."""
    __tablename__ = "inline_message_states"
    inline_message_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    inline_offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("inline_offers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (Index("ix_inline_states_offer", "inline_offer_id"),)
