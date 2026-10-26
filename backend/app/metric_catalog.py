"""Метрики, які шле агент (ТЗ 5.1, 5.3)."""
PERCENT_METRICS = {"cpu_usage", "ram_usage", "swap_usage", "disk_usage", "container_cpu", "container_mem"}
CONTAINER_METRICS = {
    "container_running", "container_health", "container_restarts", "container_oom_killed", "container_exit_code",
    "container_mem_bytes", "container_net_in", "container_net_out", "container_block_read", "container_block_write",
}
AGENT_METRICS = PERCENT_METRICS | CONTAINER_METRICS | {
    "load_avg", "cpu_cores", "load_per_core", "net_in", "net_out", "net_total", "process_count",
}
