"""Системне тестування (ТЗ 17): навантаження 50 агентів і перезапуск сервісу.

Піднімає окремий бекенд (база vigil_load, порт 8001, типовий інтервал між пакетами 5 с), реєструє користувачів,
створює сервери й імітує агентів, що надсилають по 11 метрик кожні 15 с. Вимірює:
  - час відповіді /api/ingest;
  - затримку від надсилання пакета до події «metrics» у WebSocket власника (вимога ТЗ: не більше 5 с);
  - відновлення після перезапуску бекенда: час до готовності й збереження вже записаної історії.
Потрібні Docker із контейнером бази (docker compose up -d db) і .venv бекенда.

    backend/.venv/Scripts/python.exe scripts/load_test.py [агентів] [секунд]
"""
import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PORT = 8001
BASE = f"http://127.0.0.1:{PORT}"
AGENTS = int(sys.argv[1]) if len(sys.argv) > 1 else 50
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 120
INTERVAL = 15
PER_USER = 17  # квота: 20 об'єктів на користувача
PASSWORD = "Passw0rd1"

dotenv = (ROOT / ".env").read_text(encoding="utf8")
get = lambda k: (re.search(rf"^{k}=(.*)$", dotenv, re.M) or [None, ""])[1].strip()  # noqa: E731
PG_USER = get("POSTGRES_USER") or "vigil"
DB_URL = re.sub(r"/[^/]+$", "/vigil_load", get("DATABASE_URL"))
ENV = {**os.environ, "DATABASE_URL": DB_URL, "JWT_SECRET": "load-secret-at-least-32-characters-long-000",
       "TELEGRAM_BOT_TOKEN": "", "SMTP_HOST": "", "REGISTRATION_MODE": "open", "RATE_REGISTER_PER_MIN": "100"}
PY = sys.executable


def psql(sql: str, db: str = "postgres") -> str:
    out = subprocess.run(["docker", "exec", "vigil-db-1", "psql", "-U", PG_USER, "-d", db, "-tAc", sql],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def start_server() -> subprocess.Popen:
    p = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--workers", "1"],
                         cwd=BACKEND, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def wait_ready(timeout: float = 60) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                return time.monotonic() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SystemExit("бекенд не піднявся")


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))]


def stats(name: str, values: list[float], unit: str = "мс") -> None:
    if not values:
        print(f"{name}: немає даних")
        return
    print(f"{name}: n={len(values)} середнє={statistics.mean(values):.0f} {unit}, p50={pct(values, .5):.0f}, "
          f"p95={pct(values, .95):.0f}, макс={max(values):.0f}")


def records(host: str) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat()
    base = [("cpu_usage", 35.0), ("ram_usage", 52.0), ("swap_usage", 3.0), ("process_count", 180.0), ("cpu_cores", 4.0),
            ("load_avg", 0.8), ("load_per_core", 0.2), ("net_in", 1200.0), ("net_out", 800.0), ("net_total", 2000.0)]
    return [{"host": host, "metric": m, "instance": "", "value": v, "timestamp": ts} for m, v in base] + [
        {"host": host, "metric": "disk_usage", "instance": "/", "value": 41.0, "timestamp": ts}]


async def prepare() -> list[dict]:
    """Користувачі й сервери: [{user, jwt, id, name, token}]."""
    agents = []
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        n = 0
        for u in range((AGENTS + PER_USER - 1) // PER_USER):
            email = f"load-{u}-{int(time.time())}@example.com"
            r = await c.post("/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": f"Тест {u}"})
            jwt = r.json()["access_token"]
            for _ in range(PER_USER):
                if n >= AGENTS:
                    break
                n += 1
                name = f"srv-{n:02d}"
                t = (await c.post("/api/targets", json={"name": name, "type": "server"},
                                  headers={"Authorization": f"Bearer {jwt}"})).json()
                agents.append({"user": u, "jwt": jwt, "id": t["id"], "name": name, "token": t["agent_token"]})
    return agents


async def listen(jwt: str, sent: dict[int, float], lat: list[float], stop: asyncio.Event) -> None:
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/ws") as ws:
        await ws.send(json.dumps({"type": "auth", "token": jwt}))
        while not stop.is_set():
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "metrics" and msg["target_id"] in sent:
                t0 = sent.pop(msg["target_id"], None)
                if t0 is not None:
                    lat.append((time.monotonic() - t0) * 1000)


async def agent(a: dict, offset: float, until: float, post_ms: list[float], errors: list[str], sent: dict[int, float]) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30, headers={"Authorization": f"Bearer {a['token']}"}) as c:
        await asyncio.sleep(offset)
        while time.monotonic() < until:
            t0 = time.monotonic()
            sent[a["id"]] = t0
            try:
                r = await c.post("/api/ingest", json=records(a["name"]))
                post_ms.append((time.monotonic() - t0) * 1000)
                if r.status_code != 200:
                    errors.append(f"{a['name']}: {r.status_code} {r.text[:80]}")
            except httpx.HTTPError as e:
                errors.append(f"{a['name']}: {type(e).__name__}")
            await asyncio.sleep(max(0, INTERVAL - (time.monotonic() - t0)))


async def load_phase(agents: list[dict]) -> int:
    post_ms: list[float] = []
    ws_ms: list[float] = []
    errors: list[str] = []
    sents = [dict() for _ in range(max(a["user"] for a in agents) + 1)]
    stop = asyncio.Event()
    until = time.monotonic() + SECONDS
    listeners = [asyncio.create_task(listen(next(a["jwt"] for a in agents if a["user"] == u), sents[u], ws_ms, stop))
                 for u in range(len(sents))]
    await asyncio.sleep(1)
    # події WS шукають час надсилання за target_id: словник один на користувача, але ключі – унікальні id серверів
    tasks = [asyncio.create_task(agent(a, i * INTERVAL / len(agents), until, post_ms, errors, sents[a["user"]]))
             for i, a in enumerate(agents)]
    await asyncio.gather(*tasks)
    await asyncio.sleep(2)
    stop.set()
    await asyncio.gather(*listeners)
    print(f"\n== Навантаження: {len(agents)} агентів, {SECONDS} с, по {len(records('x'))} метрик кожні {INTERVAL} с")
    stats("Відповідь /api/ingest", post_ms)
    stats("Затримка до події WebSocket", ws_ms)
    over = sum(1 for v in ws_ms if v > 5000)
    print(f"Пакетів: {len(post_ms)}, помилок: {len(errors)}, затримка понад 5 с: {over}")
    for e in errors[:5]:
        print("  ", e)
    return len(post_ms)


def main() -> None:
    psql("DROP DATABASE IF EXISTS vigil_load WITH (FORCE)")
    psql("CREATE DATABASE vigil_load")
    subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=ENV, check=True, capture_output=True)
    subprocess.run([PY, "seed.py"], cwd=BACKEND, env=ENV, check=True, capture_output=True)
    server = start_server()
    try:
        ready = wait_ready()
        print(f"Бекенд готовий за {ready:.1f} с")
        agents = asyncio.run(prepare())
        sent_packets = asyncio.run(load_phase(agents))
        before = int(psql("SELECT count(*) FROM metrics", "vigil_load"))
        print(f"\nУ базі {before} значень метрик")

        print("\n== Перезапуск бекенда")
        server.terminate()
        server.wait(10)
        t0 = time.monotonic()
        server = start_server()
        ready = wait_ready()
        a = agents[0]
        r = httpx.post(f"{BASE}/api/ingest", json=records(a["name"]), headers={"Authorization": f"Bearer {a['token']}"})
        first_ok = time.monotonic() - t0
        after = int(psql("SELECT count(*) FROM metrics", "vigil_load"))
        print(f"Сервіс готовий за {ready:.1f} с, перший пакет агента прийнято за {first_ok:.1f} с (код {r.status_code})")
        print(f"Метрик до перезапуску: {before}, після: {after} (втрат {max(0, before - after)})")
        print(f"Пакетів надіслано за час навантаження: {sent_packets}")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
