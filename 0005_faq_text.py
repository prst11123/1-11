"""Allow long admin-editable FAQ text in app_settings."""
from alembic import op
import sqlalchemy as sa

revision="0005_faq_text"
down_revision="0004_inline_offers"
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("value", existing_type=sa.String(length=256), type_=sa.Text(), existing_nullable=False)


def downgrade():
    # FAQ can be longer than 256 characters, so intentionally do not truncate stored data.
    # This rollback requires removing long values first.
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("value", existing_type=sa.Text(), type_=sa.String(length=256), existing_nullable=False)
