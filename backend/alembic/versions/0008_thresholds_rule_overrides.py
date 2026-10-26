"""thresholds (власні пороги: шаблон користувача й окремого об'єкта) і rule_overrides (вимкнені базові правила)

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thresholds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.BigInteger(), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=True),  # NULL – шаблон для всіх об'єктів
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("warn_value", sa.Float(), nullable=True),
        sa.Column("crit_value", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.CheckConstraint("duration_s >= 0 AND duration_s <= 3600"),
    )
    op.create_index("uq_thresholds_scope", "thresholds", ["owner_id", "target_id", "metric"], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table(
        "rule_overrides",
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rule_id", sa.BigInteger(), sa.ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rule_overrides")
    op.drop_index("uq_thresholds_scope", table_name="thresholds")
    op.drop_table("thresholds")
