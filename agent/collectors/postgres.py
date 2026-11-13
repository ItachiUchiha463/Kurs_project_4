"""PostgreSQL (ТЗ 5.4): лише читання статистики. Облікові дані лишаються в agent.toml і на сервер Vigil не передаються.

Агент підключається до бази клієнта окремим користувачем із роллю pg_monitor (лише читання системних подань)
і щоразу збирає зведену статистику: з'єднання, активні запити, блокування, розмір, влучання в кеш, транзакції за секунду.
Пароль від бази ніколи не залишає сервер клієнта: у Vigil потрапляють тільки числа.
"""
import time

Sample = tuple[str, str, float]  # (metric, instance, value)

# SQL-запити до системних подань PostgreSQL. Усі лише читають.
# ACTIVITY: кількість з'єднань усього / активних / «idle in transaction» і тривалість найдовшого активного запиту, с.
ACTIVITY = """SELECT count(*),
  count(*) FILTER (WHERE state = 'active'),
  count(*) FILTER (WHERE state = 'idle in transaction'),
  coalesce(max(extract(epoch FROM now() - query_start)) FILTER (WHERE state = 'active'), 0)
FROM pg_stat_activity WHERE backend_type = 'client backend'"""
# STATS: накопичувальні лічильники (транзакції, відкати, звернення до кешу й диска, взаємоблокування, тимчасові файли).
STATS = """SELECT coalesce(sum(xact_commit), 0), coalesce(sum(xact_rollback), 0), coalesce(sum(blks_hit), 0),
  coalesce(sum(blks_read), 0), coalesce(sum(deadlocks), 0), coalesce(sum(temp_bytes), 0) FROM pg_stat_database"""
SIZES = "SELECT datname, pg_database_size(datname) FROM pg_database WHERE NOT datistemplate"  # розмір кожної бази
LOCKS = "SELECT count(*) FROM pg_locks WHERE NOT granted"  # запити, що чекають блокування
LAG = "SELECT extract(epoch FROM now() - pg_last_xact_replay_timestamp()) WHERE pg_is_in_recovery()"  # відставання репліки


def _connect(dsn: str):
    """Підключення до PostgreSQL. Драйвер psycopg імпортується лише тут, щоб агент без баз його не вимагав."""
    import psycopg  # імпорт тут: агент без баз даних не потребує драйвера

    return psycopg.connect(dsn, connect_timeout=5, autocommit=True, options="-c statement_timeout=5000")  # запити – не довше 5 с


class PostgresCollector:
    """Збирач метрик однієї бази PostgreSQL."""

    def __init__(self, dsn: str, connect=None):
        # connect можна підмінити в тестах (без справжньої бази).
        self.dsn, self.connect = dsn, connect or _connect
        self._prev: tuple[float, float, float, float, float, float, float] | None = None  # t, commits, rollbacks, hit, read, deadlocks, temp

    def collect(self) -> list[Sample]:
        """Якщо БД не відповідає, надсилається лише db_up = 0 (решта метрик за цей цикл не потрібна)."""
        try:
            conn = self.connect(self.dsn)
        except Exception:  # noqa: BLE001 – будь-яка помилка підключення означає «БД недоступна»
            return [("db_up", "", 0.0)]
        try:
            t0 = time.perf_counter()  # час самого запиту: підключення (DNS, TLS) до db_response_ms не входить
            conn.execute("SELECT 1")
            out: list[Sample] = [("db_up", "", 1.0), ("db_response_ms", "", (time.perf_counter() - t0) * 1000)]
            max_conn = float(conn.execute("SHOW max_connections").fetchone()[0])
            total, active, idle_tx, longest = (float(x) for x in conn.execute(ACTIVITY).fetchone())
            # З'єднання: кількість і відсоток від максимуму (поріг «вичерпано пул з'єднань» працює за відсотком).
            out += [("db_connections", "", total), ("db_connections_pct", "", min(100.0, total / max_conn * 100) if max_conn else 0.0),
                    ("db_active_queries", "", active), ("db_idle_in_tx", "", idle_tx), ("db_longest_query_s", "", longest)]
            out += self._rates(*(float(x) for x in conn.execute(STATS).fetchone()))
            out.append(("db_locks_waiting", "", float(conn.execute(LOCKS).fetchone()[0])))
            out += [("db_size_mb", name, size / 1024 / 1024) for name, size in conn.execute(SIZES).fetchall()]
            lag = conn.execute(LAG).fetchone()
            if lag and lag[0] is not None:
                out.append(("db_replication_lag_s", "", float(lag[0])))  # лише на репліці
            return out
        except Exception:  # noqa: BLE001 – обрив посеред збору: БД вважаємо недоступною
            return [("db_up", "", 0.0)]
        finally:
            conn.close()

    def _rates(self, commits: float, rollbacks: float, hit: float, read: float, deadlocks: float, temp: float) -> list[Sample]:
        """Швидкості за лічильниками: транзакції/с, відкати/с, взаємоблокування, тимчасові файли; а також % влучань у кеш."""
        now, prev = time.monotonic(), self._prev
        self._prev = (now, commits, rollbacks, hit, read, deadlocks, temp)
        # Влучання в кеш рахується за приростом з попереднього циклу; на першому циклі – за накопиченими значеннями.
        dhit, dread = (hit - prev[3], read - prev[4]) if prev else (hit, read)
        if dhit + dread <= 0:  # за цикл жодного звернення до кешу: беремо накопичене значення
            dhit, dread = hit, read
        out: list[Sample] = [("db_cache_hit_pct", "", dhit / (dhit + dread) * 100 if dhit + dread > 0 else 100.0)]
        if prev:
            dt = max(now - prev[0], 1e-3)
            out += [("db_tps", "", max(commits + rollbacks - prev[1] - prev[2], 0) / dt),
                    ("db_rollbacks_ps", "", max(rollbacks - prev[2], 0) / dt),
                    ("db_deadlocks", "", max(deadlocks - prev[5], 0)),
                    ("db_temp_bytes_ps", "", max(temp - prev[6], 0) / dt)]
        return out
