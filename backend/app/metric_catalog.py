"""Метрики, які шле агент (ТЗ 5.1)."""
PERCENT_METRICS = {"cpu_usage", "ram_usage", "swap_usage", "disk_usage"}
AGENT_METRICS = PERCENT_METRICS | {
    "load_avg", "cpu_cores", "load_per_core", "net_in", "net_out", "net_total", "process_count",
}
