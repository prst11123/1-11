"""Enable inline DEMO offers in chats outside the Business reply window."""
from alembic import op
import sqlalchemy as sa

revision = "0004_inline_offers"
down_revision = "0003_demo_contact_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inline_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("gift_url", sa.String(length=400), nullable=False),
        sa.Column("gift_name", sa.String(length=150), nullable=False),
        sa.Column("stars_amount", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inline_offers_expiry", "inline_offers", ["expires_at"])
    op.create_table("inline_message_states",
        sa.Column("inline_message_id", sa.String(length=512), primary_key=True),
        sa.Column("inline_offer_id", sa.Integer(), sa.ForeignKey("inline_offers.id"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inline_states_offer", "inline_message_states", ["inline_offer_id"])


def downgrade():
    op.drop_index("ix_inline_states_offer", table_name="inline_message_states")
    op.drop_table("inline_message_states")
    op.drop_index("ix_inline_offers_expiry", table_name="inline_offers")
    op.drop_table("inline_offers")
