"""безперервний агрегат metrics_5m (графіки 7/30 днів) і стиснення старих блоків (ТЗ 4.1)

Revision ID: 0007
Revises: 0006
"""
from alembic import op

from app.config import settings

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # безперервний агрегат і політики TimescaleDB не можна створювати всередині транзакції
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE MATERIALIZED VIEW metrics_5m WITH (timescaledb.continuous) AS
            SELECT time_bucket(INTERVAL '5 minutes', ts) AS bucket, target_id, name, instance,
                   avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value
            FROM metrics GROUP BY bucket, target_id, name, instance WITH NO DATA""")
        op.execute("""SELECT add_continuous_aggregate_policy('metrics_5m', start_offset => INTERVAL '2 days',
                      end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes')""")
        op.execute(f"SELECT add_retention_policy('metrics_5m', INTERVAL '{settings.metrics_retention_days} days')")
        op.execute("""ALTER TABLE metrics SET (timescaledb.compress, timescaledb.compress_segmentby = 'target_id, name, instance',
                      timescaledb.compress_orderby = 'ts DESC')""")
        op.execute("SELECT add_compression_policy('metrics', INTERVAL '1 day')")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SELECT remove_compression_policy('metrics', if_exists => true)")
        op.execute("ALTER TABLE metrics SET (timescaledb.compress = false)")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS metrics_5m")
