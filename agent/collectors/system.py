"""Метрики сервера (ТЗ 5.1). Повертає список (metric, instance, value).

Усе збирається бібліотекою psutil, яка однаково працює в Linux і Windows. Результат – плоский список трійок
(метрика, instance, значення). instance потрібен лише для метрик «за диском» (disk_usage, inode_usage): тоді це
точка монтування («/», «C:»); для решти він порожній.

Метрики-лічильники (мережа, дисковий I/O) у ОС лише ЗРОСТАЮТЬ з моменту запуску, тож швидкість рахується як
(значення зараз – значення минулого разу) / (скільки секунд минуло). Тому колектор запам'ятовує попередній знімок.
"""
import os
import time

import psutil

Sample = tuple[str, str, float]


class SystemCollector:
    """Збирає метрики самого сервера. Один екземпляр живе весь час роботи агента (щоб пам'ятати попередні лічильники)."""

    def __init__(self, disks: list[str] | None = None):
        self.disks = disks or []  # які диски моніторити; порожньо – усі
        # Початкові знімки лічильників: від них рахується швидкість на першому циклі.
        self._net = (time.monotonic(), psutil.net_io_counters())
        self._io = (time.monotonic(), psutil.disk_io_counters())  # None, якщо в системі немає дисків (контейнер)
        psutil.cpu_percent(None)  # перший виклик завжди повертає 0, тож «прогріваємо» лічильник
        psutil.cpu_times_percent(None)

    def collect(self) -> list[Sample]:
        """Одне опитування: повертає всі метрики сервера на цей момент."""
        out: list[Sample] = [
            ("cpu_usage", "", psutil.cpu_percent(None)),  # None: частка з моменту попереднього виклику (не блокує)
            ("ram_usage", "", psutil.virtual_memory().percent),
            ("swap_usage", "", psutil.swap_memory().percent),
            ("process_count", "", float(len(psutil.pids()))),
            ("ram_available_mb", "", psutil.virtual_memory().available / 1024 / 1024),  # вільна пам'ять без кешу, МБ
            ("uptime_h", "", (time.time() - psutil.boot_time()) / 3600),  # скільки годин сервер працює з останнього завантаження
        ]
        times = psutil.cpu_times_percent(None)
        for field in ("iowait", "steal"):  # лише Linux
            # iowait – процесор простоює, чекаючи диск; steal – віртуальна машина втрачає час через сусідів на хості.
            if hasattr(times, field):
                out.append((f"cpu_{field}", "", getattr(times, field)))
        cores = psutil.cpu_count(logical=True) or 1
        out.append(("cpu_cores", "", float(cores)))
        if hasattr(os, "getloadavg"):  # лише Linux
            # Середнє навантаження за хвилину, а також на одне ядро (щоб порівнювати сервери з різним числом ядер).
            load = os.getloadavg()[0]
            out += [("load_avg", "", load), ("load_per_core", "", load / cores)]
        out += self._network()
        out += self._disk_io()
        out += self._disks()
        return out

    def _network(self) -> list[Sample]:
        """Швидкість мережі, КБ/с: різниця лічильників байтів / час між опитуваннями."""
        now, counters = time.monotonic(), psutil.net_io_counters()
        t0, prev = self._net
        self._net = (now, counters)
        dt = max(now - t0, 1e-3)  # max(…, 1e-3): захист від ділення на нуль
        net_in = (counters.bytes_recv - prev.bytes_recv) / 1024 / dt
        net_out = (counters.bytes_sent - prev.bytes_sent) / 1024 / dt
        return [("net_in", "", net_in), ("net_out", "", net_out), ("net_total", "", net_in + net_out)]

    def _disk_io(self) -> list[Sample]:
        """Швидкість читання й запису диска, КБ/с (так само, як мережа)."""
        now, counters = time.monotonic(), psutil.disk_io_counters()
        t0, prev = self._io
        self._io = (now, counters)
        if counters is None or prev is None:
            return []  # у деяких середовищах (контейнер, VM без дисків) статистики немає
        dt = max(now - t0, 1e-3)
        return [("disk_read", "", (counters.read_bytes - prev.read_bytes) / 1024 / dt),
                ("disk_write", "", (counters.write_bytes - prev.write_bytes) / 1024 / dt)]

    def _disks(self) -> list[Sample]:
        """Заповненість кожного диска (%) й, на Linux, кількість зайнятих inode (%)."""
        out: list[Sample] = []
        for part in psutil.disk_partitions(all=False):  # all=False: лише справжні диски, без службових файлових систем
            mount = part.mountpoint
            if self.disks and mount.rstrip("\\/") not in {d.rstrip("\\/") for d in self.disks}:
                continue  # цей диск користувач не просив моніторити
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
