"""Persist Guest query deduplication and the exact sent message binding."""
from alembic import op
import sqlalchemy as sa

revision = "0006_guest_bindings"
down_revision = "0005_faq_text"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inline_offers", sa.Column("guest_query_id", sa.String(512), nullable=True))
    op.add_column("inline_offers", sa.Column("guest_inline_message_id", sa.String(512), nullable=True))
    op.create_index("ix_inline_offers_guest_query", "inline_offers", ["guest_query_id"], unique=True)
    op.create_index("ix_inline_offers_guest_message", "inline_offers", ["guest_inline_message_id"], unique=True)


def downgrade():
    op.drop_index("ix_inline_offers_guest_message", table_name="inline_offers")
    op.drop_index("ix_inline_offers_guest_query", table_name="inline_offers")
    op.drop_column("inline_offers", "guest_inline_message_id")
    op.drop_column("inline_offers", "guest_query_id")
