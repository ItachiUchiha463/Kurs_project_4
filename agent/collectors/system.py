"""Метрики сервера (ТЗ 5.1). Повертає список (metric, instance, value)."""
import os
import time

import psutil

Sample = tuple[str, str, float]


class SystemCollector:
    def __init__(self, disks: list[str] | None = None):
        self.disks = disks or []
        self._net = (time.monotonic(), psutil.net_io_counters())
        psutil.cpu_percent(None)  # перший виклик завжди повертає 0, тож «прогріваємо» лічильник

    def collect(self) -> list[Sample]:
        out: list[Sample] = [
            ("cpu_usage", "", psutil.cpu_percent(None)),
            ("ram_usage", "", psutil.virtual_memory().percent),
            ("swap_usage", "", psutil.swap_memory().percent),
            ("process_count", "", float(len(psutil.pids()))),
        ]
        cores = psutil.cpu_count(logical=True) or 1
        out.append(("cpu_cores", "", float(cores)))
        if hasattr(os, "getloadavg"):  # лише Linux
            load = os.getloadavg()[0]
            out += [("load_avg", "", load), ("load_per_core", "", load / cores)]
        out += self._network()
        out += self._disks()
        return out

    def _network(self) -> list[Sample]:
        now, counters = time.monotonic(), psutil.net_io_counters()
        t0, prev = self._net
        self._net = (now, counters)
        dt = max(now - t0, 1e-3)
        net_in = (counters.bytes_recv - prev.bytes_recv) / 1024 / dt
        net_out = (counters.bytes_sent - prev.bytes_sent) / 1024 / dt
        return [("net_in", "", net_in), ("net_out", "", net_out), ("net_total", "", net_in + net_out)]

    def _disks(self) -> list[Sample]:
        out: list[Sample] = []
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if self.disks and mount.rstrip("\\/") not in {d.rstrip("\\/") for d in self.disks}:
                continue
            try:
                out.append(("disk_usage", mount.rstrip("\\") or mount, psutil.disk_usage(mount).percent))
            except OSError:  # знімний диск без носія, недоступний розділ
                continue
        return out
