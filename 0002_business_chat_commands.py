"""Deduplicate offers created from a Business owner's chat message."""
from alembic import op
import sqlalchemy as sa

revision = "0002_business_chat_commands"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offers") as batch:
        batch.add_column(sa.Column("source_message_id", sa.BigInteger(), nullable=True))
        batch.create_unique_constraint("uq_offer_business_command", ["business_connection_id", "recipient_chat_id", "source_message_id"])


def downgrade():
    with op.batch_alter_table("offers") as batch:
        batch.drop_constraint("uq_offer_business_command", type_="unique")
        batch.drop_column("source_message_id")
