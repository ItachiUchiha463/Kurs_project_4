"""Docker-контейнери (ТЗ 5.3): читаємо лише Docker Engine API (через docker-socket-proxy на Linux), нічого не змінюємо."""
import fnmatch
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger("vigil-agent")
HEALTH = {"unhealthy": 0, "starting": 1, "healthy": 2}
WORKERS = 10  # одночасних запитів stats (ТЗ 5.3)

Sample = tuple[str, str, float]  # (container_id, metric, value)


def client_for(url: str) -> httpx.Client:
    """tcp://host:port або unix:///шлях; npipe (Docker Desktop на Windows) не підтримується – див. DEPLOY.md."""
    if url.startswith("unix://"):
        return httpx.Client(transport=httpx.HTTPTransport(uds=url.removeprefix("unix://")), base_url="http://docker", timeout=10)
    if url.startswith("tcp://"):
        return httpx.Client(base_url="http://" + url.removeprefix("tcp://"), timeout=10)
    raise ValueError("docker_url: підтримуються tcp://host:port і unix:///шлях")


def _cpu_pct(stats: dict) -> float:
    cpu, pre = stats.get("cpu_stats", {}), stats.get("precpu_stats", {})
    d_cpu = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
    d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    # без множення на кількість ядер: 90 % означає те саме на 2- і на 16-ядерній машині
    return max(0.0, min(100.0, d_cpu / d_sys * 100)) if d_sys > 0 and d_cpu >= 0 else 0.0


def _mem(stats: dict) -> tuple[float, float]:
    m = stats.get("memory_stats", {})
    inner = m.get("stats", {})
    used = m.get("usage", 0) - inner.get("inactive_file", inner.get("cache", 0))  # без кешу
    limit = m.get("limit") or 0
    return (max(0.0, min(100.0, used / limit * 100)) if limit else 0.0), max(used, 0) / 1024 / 1024


def _net(stats: dict) -> tuple[int, int]:
    nets = stats.get("networks", {}).values()
    return sum(n.get("rx_bytes", 0) for n in nets), sum(n.get("tx_bytes", 0) for n in nets)


def _block(stats: dict) -> tuple[int, int]:
    rd = wr = 0
    for e in stats.get("blkio_stats", {}).get("io_service_bytes_recursive") or []:
        op = e.get("op", "").lower()
        if op == "read":
            rd += e.get("value", 0)
        elif op == "write":
            wr += e.get("value", 0)
    return rd, wr


class DockerCollector:
    def __init__(self, client: httpx.Client, ignore: list[str] | None = None):
        self.client, self.ignore = client, ignore or []
        self._prev: dict[str, tuple[float, int, int, int, int]] = {}  # id -> (t, rx, tx, read, write)

    def _skip(self, c: dict) -> bool:
        names = [n.lstrip("/") for n in c.get("Names", [])]
        return c.get("Labels", {}).get("vigil.ignore") == "true" or any(fnmatch.fnmatch(n, m) for n in names for m in self.ignore)

    def _one(self, c: dict) -> tuple[dict, list[Sample]]:
        cid = c["Id"][:12]
        info = {"id": cid, "name": c["Names"][0].lstrip("/") if c.get("Names") else cid, "image": c.get("Image", ""),
                "state": c.get("State", "")}
        detail = self.client.get(f"/containers/{cid}/json").raise_for_status().json()
        st = detail["State"]
        run = bool(st.get("Running"))
        s: list[Sample] = [(cid, "container_running", float(run)), (cid, "container_oom_killed", float(bool(st.get("OOMKilled")))),
                           (cid, "container_restarts", float(detail.get("RestartCount", 0)))]
        if st.get("Health", {}).get("Status") in HEALTH:
            s.append((cid, "container_health", float(HEALTH[st["Health"]["Status"]])))
        if not run:
            s.append((cid, "container_exit_code", float(st.get("ExitCode", 0))))
            return info, s
        stats = self.client.get(f"/containers/{cid}/stats", params={"stream": "false"}).raise_for_status().json()
        mem_pct, mem_mb = _mem(stats)
        s += [(cid, "container_cpu", _cpu_pct(stats)), (cid, "container_mem", mem_pct), (cid, "container_mem_bytes", mem_mb)]
        now, (rx, tx), (rd, wr) = time.monotonic(), _net(stats), _block(stats)
        if cid in self._prev:
            t0, rx0, tx0, rd0, wr0 = self._prev[cid]
            dt = max(now - t0, 1e-3)
            s += [(cid, "container_net_in", max(rx - rx0, 0) / 1024 / dt), (cid, "container_net_out", max(tx - tx0, 0) / 1024 / dt),
                  (cid, "container_block_read", max(rd - rd0, 0) / 1024 / dt), (cid, "container_block_write", max(wr - wr0, 0) / 1024 / dt)]
        self._prev[cid] = (now, rx, tx, rd, wr)
        return info, s

    def collect(self) -> tuple[list[dict], list[Sample]]:
        """(список контейнерів, значення метрик); контейнер, який не вдалося прочитати, пропускається."""
        found = [c for c in self.client.get("/containers/json", params={"all": "true"}).raise_for_status().json() if not self._skip(c)]
        infos, samples = [], []

        def safe(c):
            try:
                return self._one(c)
            except (httpx.HTTPError, KeyError, ValueError) as e:  # контейнер міг зникнути між запитами
                log.warning("контейнер %s пропущено: %s", c.get("Id", "?")[:12], type(e).__name__)
                return None

        with ThreadPoolExecutor(WORKERS) as pool:
            for res in pool.map(safe, found):
                if res:
                    infos.append(res[0])
                    samples += res[1]
        return infos, samples
