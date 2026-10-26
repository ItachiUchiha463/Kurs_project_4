"""Системні типові пороги (ТЗ 7.3) для метрик, що вже збираються. Нові додаються разом зі збирачами."""
from app.engine.thresholds import Threshold

_T = Threshold
DEFAULT_THRESHOLDS: dict[str, Threshold] = {t.metric: t for t in [
    _T("cpu_usage", "avg", 120, warn=80, crit=95, duration_s=0),
    _T("ram_usage", "avg", 120, warn=85, crit=95, duration_s=0),
    _T("load_per_core", "avg", 300, warn=1.5, crit=3, duration_s=0),
    _T("disk_usage", "last", 0, warn=85, crit=95, duration_s=60),
    _T("response_ms", "avg", 60, warn=1000, crit=3000, duration_s=0),
    _T("packet_loss", "avg", 60, warn=10, crit=50, duration_s=0),
    # бінарні метрики: лише crit, без гістерезису
    _T("available", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("ping_available", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("agent_alive", "last", 0, crit=0, direction="equals", duration_s=0),
    # контейнери (ТЗ 5.3, 7.3)
    _T("container_running", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("container_oom_killed", "last", 0, crit=1, direction="equals", duration_s=0),
    _T("container_health", "last", 0, crit=0, direction="equals", duration_s=60),
    _T("container_mem", "avg", 120, warn=85, crit=95, duration_s=0),
    _T("container_cpu", "avg", 300, warn=80, crit=95, duration_s=0),
    _T("container_restarts", "delta", 600, warn=0, crit=2, duration_s=0),
    # бази даних (ТЗ 5.4, 7.3); ціле «≥ N» записано як «> N − 1»
    _T("db_up", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("db_connections_pct", "last", 0, warn=80, crit=95, duration_s=60),
    _T("db_idle_in_tx", "last", 0, warn=5, crit=20, duration_s=60),
    _T("db_longest_query_s", "last", 0, warn=30, crit=300, duration_s=0),
    _T("db_locks_waiting", "last", 0, warn=0, crit=9, duration_s=60),
    _T("db_cache_hit_pct", "avg", 900, warn=95, crit=90, direction="below", duration_s=0),  # ≥ 1 і ≥ 3 перезапусків за 10 хв (лічильник цілий)
]}

# метрики, інцидент на яких робить об'єкт «недоступним», а не «критичним» (ТЗ 7.2)
SERVER_AVAILABILITY = ("agent_alive", "ping_available")  # інцидент на цих метриках робить сервер недоступним (ТЗ 7.1.1)
AVAILABILITY_METRICS = {"available", *SERVER_AVAILABILITY, "container_running", "db_up"}
