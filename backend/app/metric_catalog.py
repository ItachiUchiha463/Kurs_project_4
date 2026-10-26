"""Метрики, які шле агент (ТЗ 5.1, 5.3)."""
PERCENT_METRICS = {"cpu_usage", "ram_usage", "swap_usage", "disk_usage", "container_cpu", "container_mem",
                   "db_connections_pct", "db_cache_hit_pct"}
DB_METRICS = {
    "db_up", "db_response_ms", "db_connections", "db_active_queries", "db_idle_in_tx", "db_longest_query_s", "db_tps",
    "db_rollbacks_ps", "db_deadlocks", "db_temp_bytes_ps", "db_size_mb", "db_locks_waiting", "db_replication_lag_s",
}
CONTAINER_METRICS = {
    "container_running", "container_health", "container_restarts", "container_oom_killed", "container_exit_code",
    "container_mem_bytes", "container_net_in", "container_net_out", "container_block_read", "container_block_write",
}
SERVER_SIDE_METRICS = {  # метрики перевірок із боку сервера й агента-життєздатності
    "available", "response_ms", "status_code", "packet_loss", "ping_available", "ping_ms", "agent_alive",
}
AGENT_METRICS = PERCENT_METRICS | CONTAINER_METRICS | DB_METRICS | {
    "load_avg", "cpu_cores", "load_per_core", "net_in", "net_out", "net_total", "process_count",
}
KNOWN_METRICS = AGENT_METRICS | SERVER_SIDE_METRICS  # метрики, що можна вказувати в умовах власних правил
