"""Регресійні тести до знахідок аудиту (кожен тест падає, якщо відповідну помилку повернуть)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import tasks
from app.config import Settings, settings
from app.db import SessionLocal, engine
from app.realtime.hub import Hub
from app.services import checks, ingest, pipeline
from tests.test_background import age_breach, ping_agent, service
from tests.test_incidents import incidents, push, server
from tests.test_targets import rec

# ---------- 1. коміт виконується до відправки відповіді ----------


async def test_db_commit_happens_before_response_is_sent(monkeypatch):
    import app.db as db_module
    from app.main import app

    events: list[str] = []

    class Spy(AsyncSession):
        async def commit(self):
            events.append("commit")
            await super().commit()

    monkeypatch.setattr(db_module, "SessionLocal", async_sessionmaker(engine, class_=Spy, expire_on_commit=False))
    scope = {"type": "http", "method": "GET", "path": "/api/health", "headers": [], "query_string": b"", "scheme": "http",
             "server": ("t", 80), "client": ("c", 1), "http_version": "1.1", "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            events.append("response")

    await app(scope, receive, send)
    assert events.index("commit") < events.index("response"), events


# ---------- 2. слабкий секрет не приймається ----------

@pytest.mark.parametrize("secret", ["", "short", "change-me-48-random-chars", "dev-only-change-me", "x" * 31])
def test_weak_jwt_secret_is_refused(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=secret)


def test_strong_jwt_secret_is_accepted():
    assert Settings(_env_file=None, jwt_secret="a" * 40).jwt_secret == "a" * 40


# ---------- 3. обмеження реєстрації та входу ----------

REG = "/api/auth/register"


def reg_body(i):
    return {"email": f"u{i}@example.com", "password": "Passw0rd1", "full_name": "Користувач"}


async def test_registration_is_limited_per_ip(client):
    codes = [(await client.post(REG, json=reg_body(i))).status_code for i in range(7)]
    assert codes == [201] * 5 + [429] * 2


async def test_registration_closes_when_user_cap_is_reached(client, monkeypatch):
    monkeypatch.setattr(settings, "global_users", 1)
    assert (await client.post(REG, json=reg_body(0))).status_code == 201
    r = await client.post(REG, json=reg_body(1))
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_closed"


async def test_login_is_limited_per_ip(client):
    await client.post(REG, json=reg_body(0))
    codes = [(await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Wrong0000"})).status_code
             for _ in range(12)]
    assert 429 in codes and codes[:10].count(401) + codes[:10].count(429) == 10


async def test_ten_failed_logins_lock_the_email_even_for_correct_password(client):
    from app.api import auth as auth_api
    await client.post(REG, json=reg_body(0))
    auth_api.login_limiter.limit = 1000  # перевіряємо саме блокування за email, а не ліміт за IP
    try:
        for _ in range(10):
            assert (await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Wrong0000"})).status_code == 401
        r = await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Passw0rd1"})
        assert r.status_code == 429
        # блокування діє й на неіснуючий email: за відповіддю не дізнатися, чи є обліковий запис
        for _ in range(10):
            await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "Wrong0000"})
        ghost = await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "Wrong0000"})
        assert ghost.status_code == 429
    finally:
        auth_api.login_limiter.limit = settings.rate_login_per_min


async def test_successful_login_resets_failure_counter(client):
    from app.api import auth as auth_api
    await client.post(REG, json=reg_body(0))
    auth_api.login_limiter.limit = 1000
    try:
        for _ in range(9):
            await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Wrong0000"})
        assert (await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Passw0rd1"})).status_code == 200
        for _ in range(9):
            await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Wrong0000"})
        assert (await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Passw0rd1"})).status_code == 200
    finally:
        auth_api.login_limiter.limit = settings.rate_login_per_min


# ---------- 4. довгий пароль не дає 500 ----------

async def test_password_over_72_bytes_is_a_clear_error_not_a_crash(client):
    long_pw = "Привітсвіт" * 5 + "1"  # 51 символ = 102 байти
    r = await client.post(REG, json={**reg_body(0), "password": long_pw})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "password"
    ok_pw = "Привіт" * 5 + "1"  # 31 символ = 61 байт: цілком припустимо
    assert (await client.post(REG, json={**reg_body(1), "password": ok_pw})).status_code == 201
    assert (await client.post("/api/auth/login", json={"email": "u1@example.com", "password": ok_pw})).status_code == 200
    r = await client.post("/api/auth/login", json={"email": "u1@example.com", "password": long_pw})
    assert r.status_code == 401  # раніше – 500


# ---------- 6. видалення сервера не знищує сервіси ----------

async def test_deleting_server_keeps_its_services(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    svc = await service(client, h, host_id=srv["id"])
    assert (await client.delete(f"/api/targets/{srv['id']}", headers=h)).status_code == 204
    got = await client.get(f"/api/targets/{svc['id']}", headers=h)
    assert got.status_code == 200 and got.json()["host_id"] is None


# ---------- 7. ряди одного об'єкта обмежені ----------

async def test_overlong_instance_is_rejected_but_batch_survives(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    batch = [rec("cpu_usage", 10), rec("disk_usage", 5, instance="x" * 101), rec("disk_usage", 5, instance="/")]
    r = await client.post("/api/ingest", json=batch, headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert r.json()["accepted"] == 2 and [x["index"] for x in r.json()["rejected"]] == [1]


async def test_series_per_target_are_capped(client, user_factory, monkeypatch):
    monkeypatch.setattr(settings, "max_series_per_target", 6)
    h = await user_factory()
    srv = await server(client, h)
    batch = [rec("disk_usage", 5, instance=f"/mnt/{i}") for i in range(20)]
    r = await client.post("/api/ingest", json=batch, headers={"Authorization": f"Bearer {srv['agent_token']}"})
    body = r.json()
    assert body["accepted"] == 6 - 0 and len(body["rejected"]) == 14 and "ліміт" in body["rejected"][0]["reason"]
    # уже відомі ряди продовжують працювати, навіть коли ліміт вичерпано
    again = await client.post("/api/ingest", json=[rec("disk_usage", 6, instance="/mnt/0")],
                              headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert again.json()["accepted"] == 1


# ---------- 9. задачі не губляться ----------

async def test_spawned_task_is_referenced_until_done():
    gate = asyncio.Event()

    async def work():
        await gate.wait()

    task = tasks.spawn(work())
    assert task in tasks._tasks
    gate.set()
    await task
    await asyncio.sleep(0)
    assert task not in tasks._tasks


# ---------- 10. повільний клієнт не гальмує інших ----------

class FakeSocket:
    def __init__(self, delay=0.0):
        self.delay, self.got, self.closed = delay, [], False

    async def send_json(self, message):
        await asyncio.sleep(self.delay)
        self.got.append(message)

    async def close(self, code=1000):
        self.closed = True


async def test_stuck_socket_does_not_block_others(monkeypatch):
    from app.realtime import hub as hub_module
    monkeypatch.setattr(hub_module, "SEND_TIMEOUT_S", 0.2)
    hub, stuck, healthy = Hub(), FakeSocket(delay=30), FakeSocket()
    hub.join(1, stuck)
    hub.join(1, healthy)
    started = asyncio.get_running_loop().time()
    await hub.publish(1, {"type": "x"})
    assert asyncio.get_running_loop().time() - started < 1.5
    assert healthy.got == [{"type": "x"}] and stuck.closed and stuck not in hub.rooms.get(1, set())


# ---------- 11. ручне закриття не відкриває дубль одразу ----------

async def test_manual_close_does_not_reopen_while_value_stays_bad(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv["agent_token"], "cpu_usage", 97, ago_s=500)
    [inc] = await incidents(client, h)
    await client.post(f"/api/incidents/{inc['id']}/resolve", json={"comment": "знаю, лагоджу"}, headers=h)
    await push(client, srv["agent_token"], "cpu_usage", 98, ago_s=400)  # значення й далі погане
    assert len(await incidents(client, h)) == 1  # нового інциденту немає
    await push(client, srv["agent_token"], "cpu_usage", 10, ago_s=300)  # нормалізувалося
    await push(client, srv["agent_token"], "cpu_usage", 99, ago_s=100)  # нове порушення
    all_incidents = await incidents(client, h)
    assert len(all_incidents) == 2 and all_incidents[0]["status"] == "open"


# ---------- 12. мертвий агент не пише рядок щоразу ----------

async def test_dead_agent_is_recorded_once_not_every_cycle(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "demo-1", interval=15)
    await ping_agent(client, srv)
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    async with SessionLocal() as db:
        assert await checks.check_agents(db, future) == 1
        await db.commit()
        assert await checks.check_agents(db, future + timedelta(seconds=15)) == 0
        await db.commit()
    async with SessionLocal() as db:
        rows = (await db.execute(text("select count(*) from metrics where name = 'agent_alive' and value = 0"))).scalar()
    assert rows == 1


# ---------- 13. повільніший агент не вважається мертвим ----------

async def test_agent_with_longer_interval_is_not_marked_dead(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "demo-1", interval=30)
    await client.post("/api/ingest", json=[rec("cpu_usage", 10, host="demo-1")],
                      headers={"Authorization": f"Bearer {srv['agent_token']}", "X-Agent-Interval": "120"})
    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        assert await checks.check_agents(db, now + timedelta(seconds=150)) == 0  # 150 с < 3 × 120
        assert await checks.check_agents(db, now + timedelta(seconds=400)) == 1  # 400 с > 3 × 120


# ---------- 17. WebSocket закривається, коли токен втратив чинність ----------

async def test_open_socket_is_closed_after_session_is_revoked(client, user_factory, monkeypatch):
    import json
    import socket

    import uvicorn
    import websockets

    from app.api import ws
    from app.main import app
    monkeypatch.setattr(ws, "RECHECK_S", 0.3)
    h = await user_factory()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.02)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/api/ws") as sock:
            await sock.send(json.dumps({"type": "auth", "token": h["Authorization"].split()[1]}))
            assert json.loads(await sock.recv()) == {"type": "ready"}
            async with SessionLocal() as db:
                await db.execute(text("UPDATE users SET token_version = token_version + 1"))
                await db.commit()
            with pytest.raises(websockets.ConnectionClosed) as e:
                await asyncio.wait_for(sock.recv(), 3)
            assert e.value.rcvd.code == 4401
        # і за терміном дії токена
        h2 = await user_factory(email="b@example.com")
        monkeypatch.setattr(ws, "_now", lambda: datetime.now(timezone.utc).timestamp() + 10 * 3600)
        async with websockets.connect(f"ws://127.0.0.1:{port}/api/ws") as sock:
            await sock.send(json.dumps({"type": "auth", "token": h2["Authorization"].split()[1]}))
            assert json.loads(await sock.recv()) == {"type": "ready"}
            with pytest.raises(websockets.ConnectionClosed) as e:
                await asyncio.wait_for(sock.recv(), 3)
            assert e.value.rcvd.code == 4401
    finally:
        srv.should_exit = True
        await task


# ---------- 19. стан видаленого об'єкта прибирається ----------

async def test_deleting_target_clears_in_memory_state(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv["agent_token"], "cpu_usage", 97)
    assert any(k[0] == srv["id"] for k in pipeline._states) and srv["id"] in ingest._series_seen
    await client.delete(f"/api/targets/{srv['id']}", headers=h)
    assert not any(k[0] == srv["id"] for k in pipeline._states)
    assert srv["id"] not in ingest._series_seen and srv["id"] not in ingest._last_ingest


# ---------- аудит 3 ----------

async def test_password_hashing_does_not_block_event_loop(client):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    await client.post(REG, json=reg_body(0))  # bcrypt ~0,3 с
    t.cancel()
    assert ticks > 5  # у блокуючій версії event loop стояв би увесь час


async def test_login_lock_does_not_lock_victim_from_other_ip(client):
    from app.services import auth as auth_service
    await client.post(REG, json=reg_body(0))
    for _ in range(10):
        auth_service.login_failures.fail("u0@example.com|6.6.6.6")
    assert auth_service.login_failures.locked("u0@example.com|6.6.6.6")
    assert (await client.post("/api/auth/login", json={"email": "u0@example.com", "password": "Passw0rd1"})).status_code == 200


async def test_service_url_with_credentials_is_rejected(client, user_factory):
    h = await user_factory()
    r = await client.post("/api/targets", json={"name": "x", "type": "service", "address": "http://u:p@example.com/"}, headers=h)
    assert r.status_code == 422


async def test_bot_loop_survives_one_bad_update(monkeypatch):
    from app import background

    handled = []

    class Bot:
        calls = 0

        async def updates(self, offset):
            Bot.calls += 1
            if Bot.calls > 1:
                raise asyncio.CancelledError
            return [{"update_id": 1}, {"update_id": 2}]

    async def handle(db, bot, update):
        handled.append(update["update_id"])
        if update["update_id"] == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(background.telegram, "get_bot", lambda: Bot())
    monkeypatch.setattr(background, "handle_update", handle)
    with pytest.raises(asyncio.CancelledError):
        await background._bot_loop()
    assert handled == [1, 2]


async def test_known_series_are_reloaded_after_ttl(client, user_factory, monkeypatch):
    h = await user_factory()
    srv = await server(client, h)
    async with SessionLocal() as db:
        await ingest._known_series(db, srv["id"])
        ingest._series_seen[srv["id"]][1].add(("disk_usage", "/gone"))
        ingest._series_seen[srv["id"]] = (ingest._series_seen[srv["id"]][0] - ingest.SERIES_TTL_S - 1, ingest._series_seen[srv["id"]][1])
        assert ("disk_usage", "/gone") not in await ingest._known_series(db, srv["id"])


# ---------- аудит 4 ----------

async def test_bot_token_never_reaches_logs(caplog):
    import httpx

    from app.logging import setup_logging
    from app.notify.telegram import Bot
    setup_logging("INFO")
    caplog.set_level("INFO")
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "result": []}))
    await Bot("123:SECRET", httpx.AsyncClient(transport=t)).updates(0)
    assert "SECRET" not in caplog.text


async def test_slow_check_is_cut_off(monkeypatch):
    from app.checks import http as http_check

    async def hang(host, port):
        await asyncio.sleep(30)

    monkeypatch.setattr(http_check, "TOTAL_TIMEOUT_S", 0.2)
    result = await http_check.check_http("http://example.com/", resolver=hang)
    assert result.available == 0 and result.error == "timeout"


async def test_manual_close_refreshes_target_status(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv["agent_token"], "cpu_usage", 97, ago_s=500)
    assert (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()["status"] == "critical"
    [inc] = await incidents(client, h)
    await client.post(f"/api/incidents/{inc['id']}/resolve", json={"comment": "лагоджу"}, headers=h)
    assert (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()["status"] == "ok"
