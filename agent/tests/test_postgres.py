import json

import httpx

from agent import Sender, make_batch
from collectors.postgres import PostgresCollector


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """Відповідає на запити за фрагментом тексту; stats – значення лічильників pg_stat_database."""

    def __init__(self, stats=(100, 2, 900, 100, 0, 0), recovery=False):
        self.stats, self.recovery, self.closed = stats, recovery, False

    def execute(self, sql, *_):
        if "max_connections" in sql:
            return Cursor([("100",)])
        if "pg_stat_activity" in sql:
            return Cursor([(20, 5, 12, 41.5)])
        if "pg_stat_database" in sql:
            return Cursor([self.stats])
        if "pg_database_size" in sql:
            return Cursor([("orders", 50 * 1024 * 1024), ("postgres", 8 * 1024 * 1024)])
        if "pg_locks" in sql:
            return Cursor([(3,)])
        if "pg_last_xact_replay_timestamp" in sql:
            return Cursor([(2.5,)] if self.recovery else [])
        return Cursor([(1,)])

    def close(self):
        self.closed = True


def values(samples):
    return {(m, i): v for m, i, v in samples}


def test_first_cycle_has_gauges_but_no_rates():
    conn = FakeConn()
    v = values(PostgresCollector("dsn", lambda dsn: conn).collect())
    assert v[("db_up", "")] == 1 and v[("db_connections", "")] == 20 and v[("db_connections_pct", "")] == 20
    assert v[("db_idle_in_tx", "")] == 12 and v[("db_longest_query_s", "")] == 41.5 and v[("db_locks_waiting", "")] == 3
    assert v[("db_size_mb", "orders")] == 50 and v[("db_size_mb", "postgres")] == 8
    assert v[("db_cache_hit_pct", "")] == 90  # 900 влучань і 100 читань з диска
    assert ("db_tps", "") not in v and ("db_replication_lag_s", "") not in v
    assert conn.closed


def test_rates_and_replica_lag_from_the_second_cycle():
    stats = [(100, 2, 900, 100, 0, 0), (160, 6, 1900, 100, 2, 4096)]
    c = PostgresCollector("dsn", lambda dsn: FakeConn(stats.pop(0), recovery=True))
    c.collect()
    v = values(c.collect())
    assert v[("db_tps", "")] > 0 and v[("db_rollbacks_ps", "")] > 0
    assert v[("db_deadlocks", "")] == 2 and v[("db_temp_bytes_ps", "")] > 0
    assert v[("db_cache_hit_pct", "")] == 100  # за цикл усі звернення влучили в кеш
    assert v[("db_replication_lag_s", "")] == 2.5


def test_unreachable_database_sends_only_db_up_zero():
    def refuse(dsn):
        raise ConnectionError("refused")

    assert PostgresCollector("dsn", refuse).collect() == [("db_up", "", 0.0)]


def test_broken_connection_in_the_middle_counts_as_down():
    class Broken(FakeConn):
        def execute(self, sql, *_):
            if "pg_locks" in sql:
                raise RuntimeError("lost connection")
            return super().execute(sql)

    conn = Broken()
    assert PostgresCollector("dsn", lambda dsn: conn).collect() == [("db_up", "", 0.0)]
    assert conn.closed


def test_batch_marks_database_records_and_sender_posts_databases():
    batch = make_batch("web-01", [], [], [("orders-db", "db_size_mb", "orders", 50.0), ("orders-db", "db_up", "", 1.0)])
    assert batch[0]["target"] == "postgres:orders-db" and batch[0]["instance"] == "orders" and batch[1]["metric"] == "db_up"
    bodies = []
    s = Sender(httpx.Client(transport=httpx.MockTransport(lambda r: bodies.append(json.loads(r.read())) or httpx.Response(200, json={}))),
               "https://x.test", "vgl_t")
    s.send(batch, {"databases": [{"id": "orders-db", "name": "orders-db", "engine": "postgres"}]})
    assert bodies[0]["databases"][0]["id"] == "orders-db" and len(bodies[0]["records"]) == 2
