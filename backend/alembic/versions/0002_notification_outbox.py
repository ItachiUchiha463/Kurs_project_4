"""черга сповіщень (outbox): статус pending, спроби, тестові повідомлення

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.alter_column("notifications", "incident_id", nullable=True)  # тестове повідомлення не прив'язане до інциденту
    for name in ("kind", "status"):
        op.drop_constraint(f"notifications_{name}_check", "notifications")
    op.create_check_constraint("notifications_kind_check", "notifications", "kind in ('opened','escalated','resolved','test')")
    op.create_check_constraint("notifications_status_check", "notifications", "status in ('pending','sent','failed')")
    op.create_index("ix_notifications_pending", "notifications", ["next_attempt_at"], postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("ix_notifications_pending", table_name="notifications")
    for name in ("kind", "status"):
        op.drop_constraint(f"notifications_{name}_check", "notifications")
    op.create_check_constraint("notifications_kind_check", "notifications", "kind in ('opened','escalated','resolved')")
    op.create_check_constraint("notifications_status_check", "notifications", "status in ('sent','failed')")
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "attempts")
