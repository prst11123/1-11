"""Initial tables and indexes.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(100)), sa.Column("first_name", sa.String(200)),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_activity_at", sa.DateTime(timezone=True)))
    op.create_table("business_connections",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_connection_id", sa.String(255), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False), sa.Column("owner_username", sa.String(100)),
        sa.Column("active", sa.Boolean(), nullable=False), sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)))
    op.create_table("business_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_connection_id", sa.String(255), sa.ForeignKey("business_connections.business_connection_id"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False), sa.Column("user_id", sa.BigInteger()),
        sa.Column("username", sa.String(100)), sa.Column("first_name", sa.String(200)),
        sa.Column("last_incoming_at", sa.DateTime(timezone=True)),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), sa.UniqueConstraint("business_connection_id", "chat_id", name="uq_business_chat"))
    op.create_index("ix_business_chat_user", "business_chats", ["user_id"])
    op.create_table("recipients",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("telegram_user_id", sa.BigInteger()),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False), sa.Column("username", sa.String(100)),
        sa.Column("business_connection_id", sa.String(255), nullable=False),
        sa.Column("label", sa.String(200)), sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_connection_id", "telegram_chat_id", name="uq_recipient_chat"))
    op.create_table("offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creator_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("recipient_user_id", sa.BigInteger(), nullable=False), sa.Column("recipient_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("business_connection_id", sa.String(255), nullable=False),
        sa.Column("gift_url", sa.String(400), nullable=False), sa.Column("gift_name", sa.String(150), nullable=False),
        sa.Column("gift_image_file_id", sa.String(300)), sa.Column("media_kind", sa.String(20), nullable=False),
        sa.Column("stars_amount", sa.BigInteger(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger()), sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)), sa.Column("declined_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)), sa.Column("transfer_requested_at", sa.DateTime(timezone=True)),
        sa.Column("sending_started_at", sa.DateTime(timezone=True)),
        sa.Column("sync_needed", sa.Boolean(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stars_amount >= 1 AND stars_amount <= 1000000000000", name="ck_stars_range"))
    op.create_index("ix_offers_due", "offers", ["status", "expires_at"])
    op.create_index("ix_offers_creator", "offers", ["creator_id"])
    op.create_table("offer_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.BigInteger()), sa.Column("target_id", sa.BigInteger()),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id")),
        sa.Column("business_connection_id", sa.String(255)),
        sa.Column("metadata", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_offer_events_time", "offer_events", ["created_at"])
    op.create_index("ix_offer_events_offer", "offer_events", ["offer_id"])
    op.create_table("admin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger()), sa.Column("action", sa.String(80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("user_flows",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False), sa.Column("state", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("processed_updates", sa.Column("update_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("callback_receipts", sa.Column("callback_id", sa.String(255), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for t in ("callback_receipts", "processed_updates", "user_flows", "admin_audit_log", "offer_events", "offers", "recipients", "business_chats", "business_connections", "users"):
        op.drop_table(t)
