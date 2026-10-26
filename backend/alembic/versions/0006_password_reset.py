"""скидання пароля через Telegram: хеш одноразового токена й строк дії

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pwd_reset_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("pwd_reset_expires", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pwd_reset_expires")
    op.drop_column("users", "pwd_reset_hash")
