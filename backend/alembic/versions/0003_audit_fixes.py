"""host_id: SET NULL замість CASCADE; інтервал агента окремо від інтервалу об'єкта

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # видалення сервера не має мовчки видаляти пов'язані сервіси разом з їхньою історією
    op.drop_constraint("targets_host_id_fkey", "targets", type_="foreignkey")
    op.create_foreign_key("targets_host_id_fkey", "targets", "targets", ["host_id"], ["id"], ondelete="SET NULL")
    op.add_column("targets", sa.Column("agent_interval_s", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "agent_interval_s")
    op.drop_constraint("targets_host_id_fkey", "targets", type_="foreignkey")
    op.create_foreign_key("targets_host_id_fkey", "targets", "targets", ["host_id"], ["id"], ondelete="CASCADE")
