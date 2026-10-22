"""Агент Vigil: збирає метрики сервера й надсилає їх у сервіс (ТЗ 5.1)."""
import argparse
import logging
import time
import tomllib
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import httpx

from collectors.system import SystemCollector

VERSION = "0.1.0"
MAX_BUFFERED = 100  # пакетів, що чекають, поки відновиться зв'язок
UNAUTHORIZED_PAUSE_S = 300  # невірний токен: не засипаємо сервер запитами

log = logging.getLogger("vigil-agent")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Sender:
    """Буфер пакетів: невдалий пакет лишається в черзі й іде першим, коли зв'язок повернеться."""

    def __init__(self, client: httpx.Client, server: str, token: str):
        self.client, self.url = client, server.rstrip("/") + "/api/ingest"
        self.headers = {"Authorization": f"Bearer {token}", "X-Agent-Version": VERSION}
        self.queue: deque[list[dict]] = deque(maxlen=MAX_BUFFERED)

    def send(self, batch: list[dict]) -> int | None:
        """Повертає HTTP-код останньої відповіді, None – якщо зв'язку немає. 401 зупиняє надсилання."""
        self.queue.append(batch)
        status = 200
        while self.queue:
            try:
                r = self.client.post(self.url, json=self.queue[0], headers={**self.headers, "X-Agent-Time": now_iso()})
            except httpx.HTTPError as e:
                log.warning("немає зв'язку з сервісом: %s (у черзі %d)", e, len(self.queue))
                return None
            status = r.status_code
            if status == 401:
                log.error("сервіс відхилив токен (401): перевірте token в agent.toml")
                return status
            if status == 429 or status >= 500:
                log.warning("сервіс відповів %s, повторимо наступного циклу", status)
                return status
            if status >= 400:  # пакет некоректний: повторювати марно
                log.error("пакет відхилено (%s): %s", status, r.text[:200])
            self.queue.popleft()
        return status


def make_batch(host: str, samples: list[tuple[str, str, float]]) -> list[dict]:
    ts = now_iso()
    return [{"host": host, "metric": m, "instance": inst, "value": v, "timestamp": ts} for m, inst, v in samples]


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
    with httpx.Client(timeout=10) as client:
        sender = Sender(client, cfg["server"], cfg["token"])
        log.info("агент %s запущено, інтервал %d с", VERSION, interval)
        while True:
            time.sleep(interval)
            status = sender.send(make_batch(cfg["host"], collector.collect()))
            if status == 401:
                time.sleep(UNAUTHORIZED_PAUSE_S)


if __name__ == "__main__":
    main()
