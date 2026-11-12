"""Метрики сервера (ТЗ 5.1). Повертає список (metric, instance, value)."""
import os
import time

import psutil

Sample = tuple[str, str, float]


class SystemCollector:
    def __init__(self, disks: list[str] | None = None):
        self.disks = disks or []
        self._net = (time.monotonic(), psutil.net_io_counters())
        self._io = (time.monotonic(), psutil.disk_io_counters())  # None, якщо в системі немає дисків (контейнер)
        psutil.cpu_percent(None)  # перший виклик завжди повертає 0, тож «прогріваємо» лічильник
        psutil.cpu_times_percent(None)

    def collect(self) -> list[Sample]:
        out: list[Sample] = [
            ("cpu_usage", "", psutil.cpu_percent(None)),
            ("ram_usage", "", psutil.virtual_memory().percent),
            ("swap_usage", "", psutil.swap_memory().percent),
            ("process_count", "", float(len(psutil.pids()))),
            ("ram_available_mb", "", psutil.virtual_memory().available / 1024 / 1024),
            ("uptime_h", "", (time.time() - psutil.boot_time()) / 3600),
        ]
        times = psutil.cpu_times_percent(None)
        for field in ("iowait", "steal"):  # лише Linux
            if hasattr(times, field):
                out.append((f"cpu_{field}", "", getattr(times, field)))
        cores = psutil.cpu_count(logical=True) or 1
        out.append(("cpu_cores", "", float(cores)))
        if hasattr(os, "getloadavg"):  # лише Linux
            load = os.getloadavg()[0]
            out += [("load_avg", "", load), ("load_per_core", "", load / cores)]
        out += self._network()
        out += self._disk_io()
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

    def _disk_io(self) -> list[Sample]:
        now, counters = time.monotonic(), psutil.disk_io_counters()
        t0, prev = self._io
        self._io = (now, counters)
        if counters is None or prev is None:
            return []
        dt = max(now - t0, 1e-3)
        return [("disk_read", "", (counters.read_bytes - prev.read_bytes) / 1024 / dt),
                ("disk_write", "", (counters.write_bytes - prev.write_bytes) / 1024 / dt)]

    def _disks(self) -> list[Sample]:
        out: list[Sample] = []
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if self.disks and mount.rstrip("\\/") not in {d.rstrip("\\/") for d in self.disks}:
                continue
            try:
                name = mount.rstrip("\\") or mount
                out.append(("disk_usage", name, psutil.disk_usage(mount).percent))
                inodes = self._inodes(mount)
                if inodes is not None:
                    out.append(("inode_usage", name, inodes))
            except OSError:  # знімний диск без носія, недоступний розділ
                continue
        return out

    @staticmethod
    def _inodes(mount: str) -> float | None:
        """Зайняті inode, %: диск може бути «повним» при вільному місці. Лише Linux; ФС без inode (FAT, NTFS) пропускаємо."""
        if not hasattr(os, "statvfs"):
            return None
        try:
            st = os.statvfs(mount)
        except OSError:
            return None
        return (st.f_files - st.f_ffree) / st.f_files * 100 if st.f_files else None
