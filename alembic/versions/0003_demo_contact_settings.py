"""Persist an owner-managed DEMO support contact (not a transfer recipient)."""
from alembic import op
import sqlalchemy as sa

revision = "0003_demo_contact_settings"
down_revision = "0002_business_chat_commands"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("app_settings")
