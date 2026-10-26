"""Агент Vigil: збирає метрики сервера й надсилає їх у сервіс (ТЗ 5.1)."""
import argparse
import logging
import time
import tomllib
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import httpx

from collectors.docker import DockerCollector, client_for
from collectors.postgres import PostgresCollector
from collectors.system import SystemCollector

VERSION = "0.2.0"
MAX_RECORDS = 500  # ліміт сервісу на один запит
MAX_BUFFERED = 100  # пакетів, що чекають, поки відновиться зв'язок
UNAUTHORIZED_PAUSE_S = 300  # невірний токен: не засипаємо сервер запитами

log = logging.getLogger("vigil-agent")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Sender:
    """Буфер пакетів: невдалий пакет лишається в черзі й іде першим, коли зв'язок повернеться."""

    def __init__(self, client: httpx.Client, server: str, token: str, interval: int = 15):
        self.client, self.url = client, server.rstrip("/") + "/api/ingest"
        self.discovered: dict[str, list[dict]] = {}  # знімок «containers» / «databases»: лише останній, у чергу не потрапляє
        self.headers = {"Authorization": f"Bearer {token}", "X-Agent-Version": VERSION, "X-Agent-Interval": str(interval)}
        self.queue: deque[list[dict]] = deque(maxlen=MAX_BUFFERED)

    def _next_request(self) -> tuple[int, list[dict]]:
        """Склеює пакети з голови черги в один запит (до MAX_RECORDS записів): сервер пропускає один запит на 5 с."""
        count, records = 0, []
        for batch in self.queue:
            if records and len(records) + len(batch) > MAX_RECORDS:
                break
            records += batch
            count += 1
        return count, records

    def send(self, batch: list[dict], discovered: dict[str, list[dict]] | None = None) -> int | None:
        """Один запит за цикл. Повертає HTTP-код відповіді, None – якщо зв'язку немає. 401 зупиняє надсилання."""
        self.queue.append(batch)
        self.discovered = discovered or {}
        count, records = self._next_request()
        try:
            payload = {"records": records, **self.discovered} if self.discovered else records
            r = self.client.post(self.url, json=payload, headers={**self.headers, "X-Agent-Time": now_iso()})
        except httpx.HTTPError as e:
            log.warning("немає зв'язку з сервісом: %s (у черзі %d)", e, len(self.queue))
            return None
        if r.status_code == 401:
            log.error("сервіс відхилив токен (401): перевірте token в agent.toml")
        elif r.status_code == 429 or r.status_code >= 500:
            log.warning("сервіс відповів %s, повторимо наступного циклу", r.status_code)
        else:
            if r.status_code >= 400:  # пакет некоректний: повторювати марно
                log.error("пакет відхилено (%s): %s", r.status_code, r.text[:200])
            for _ in range(count):
                self.queue.popleft()
        return r.status_code


def make_batch(host: str, samples: list[tuple[str, str, float]], docker_samples: list[tuple[str, str, float]] = (),
               db_samples: list[tuple[str, str, str, float]] = ()) -> list[dict]:
    ts = now_iso()
    own = [{"host": host, "metric": m, "instance": inst, "value": v, "timestamp": ts} for m, inst, v in samples]
    own += [{"host": host, "target": f"docker:{cid}", "metric": m, "value": v, "timestamp": ts} for cid, m, v in docker_samples]
    return own + [{"host": host, "target": f"postgres:{name}", "metric": m, "instance": inst, "value": v, "timestamp": ts}
                  for name, m, inst, v in db_samples]


def setup_logging(path: str) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [logging.StreamHandler(), RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="agent.toml")
    ap.add_argument("--log", default="agent.log")
    args = ap.parse_args()
    cfg = tomllib.load(open(args.config, "rb"))
    setup_logging(args.log)
    interval = max(int(cfg.get("interval", 15)), 15)
    collector = SystemCollector(cfg.get("disks"))
    dbs = {d["name"]: PostgresCollector(d["dsn"]) for d in cfg.get("databases", []) if d.get("type", "postgres") == "postgres"}
    docker = DockerCollector(client_for(cfg.get("docker_url", "tcp://127.0.0.1:2375")), cfg.get("docker_ignore")) if cfg.get("docker") else None
    with httpx.Client(timeout=10) as client:
        sender = Sender(client, cfg["server"], cfg["token"], interval)
        log.info("агент %s запущено, інтервал %d с", VERSION, interval)
        while True:
            time.sleep(interval)
            discovered, docker_samples = {}, []
            if docker:
                try:
                    containers, docker_samples = docker.collect()
                    discovered["containers"] = containers
                except (httpx.HTTPError, ValueError) as e:  # Docker недоступний: система й надалі збирається
                    log.warning("Docker недоступний: %s", type(e).__name__)
            db_samples = [(name, m, inst, v) for name, c in dbs.items() for m, inst, v in c.collect()]
            if dbs:
                discovered["databases"] = [{"id": name, "name": name, "engine": "postgres"} for name in dbs]
            status = sender.send(make_batch(cfg["host"], collector.collect(), docker_samples, db_samples), discovered)
            if status == 401:
                time.sleep(UNAUTHORIZED_PAUSE_S)


if __name__ == "__main__":
    main()
