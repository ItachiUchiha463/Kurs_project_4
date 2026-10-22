import asyncio
import json
import socket

import pytest
import uvicorn
import websockets
from sqlalchemy import text

from app.db import SessionLocal
from app.realtime import hub as hub_module
from tests.test_incidents import push, server


@pytest.fixture
async def live(monkeypatch):
    """Справжній uvicorn у тому ж циклі подій, що й тести: той самий хаб, що й у клієнта ASGITransport."""
    from app.api import ws
    from app.main import app
    monkeypatch.setattr(ws, "AUTH_TIMEOUT_S", 0.4)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.02)
    yield f"ws://127.0.0.1:{port}/api/ws"
    srv.should_exit = True
    await task


async def connect(url, headers):
    ws = await websockets.connect(url)
    await ws.send(json.dumps({"type": "auth", "token": headers["Authorization"].split()[1]}))
    assert json.loads(await ws.recv()) == {"type": "ready"}
    return ws


async def next_event(ws, kind, timeout=3):
    async with asyncio.timeout(timeout):
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == kind:
                return msg


async def test_socket_without_auth_message_is_closed(live):
    async with websockets.connect(live) as ws:
        with pytest.raises(websockets.ConnectionClosed) as e:
            await asyncio.wait_for(ws.recv(), 3)
        assert e.value.rcvd.code == 4401


async def test_bad_token_is_rejected(live):
    async with websockets.connect(live) as ws:
        await ws.send(json.dumps({"type": "auth", "token": "garbage"}))
        with pytest.raises(websockets.ConnectionClosed) as e:
            await asyncio.wait_for(ws.recv(), 3)
        assert e.value.rcvd.code == 4401


async def test_revoked_session_cannot_open_socket(live, client, user_factory):
    h = await user_factory()
    async with SessionLocal() as db:
        await db.execute(text("UPDATE users SET token_version = token_version + 1"))
        await db.commit()
    async with websockets.connect(live) as ws:
        await ws.send(json.dumps({"type": "auth", "token": h["Authorization"].split()[1]}))
        with pytest.raises(websockets.ConnectionClosed) as e:
            await asyncio.wait_for(ws.recv(), 3)
        assert e.value.rcvd.code == 4401


async def test_client_gets_metrics_and_incident_events(live, client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    ws = await connect(live, h)
    try:
        await push(client, t["agent_token"], "cpu_usage", 97)
        m = await next_event(ws, "metrics")
        assert m["target_id"] == t["id"] and m["values"]["cpu_usage"] == 97 and m["status"] == "critical"
        inc = await next_event(ws, "incident")
        assert inc["change"] == "opened" and inc["incident"]["target_name"] == "web-01"
        r = await client.post(f"/api/incidents/{inc['incident']['id']}/acknowledge", headers=h)
        assert r.status_code == 200
        ack = await next_event(ws, "incident")
        assert ack["change"] == "acknowledged" and ack["incident"]["status"] == "acknowledged"
    finally:
        await ws.close()


async def test_events_never_reach_another_users_socket(live, client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    ta = await server(client, a)
    ws_a, ws_b = await connect(live, a), await connect(live, b)
    try:
        await push(client, ta["agent_token"], "cpu_usage", 97)
        await next_event(ws_a, "incident")
        with pytest.raises(TimeoutError):
            await next_event(ws_b, "metrics", timeout=0.7)
    finally:
        await ws_a.close()
        await ws_b.close()


async def test_events_are_published_only_after_commit(monkeypatch):
    sent = []

    async def record(user_id, message):
        sent.append((user_id, message))

    monkeypatch.setattr(hub_module.hub, "publish", record)
    async with SessionLocal() as db:
        hub_module.publish_after_commit(db, 1, {"type": "x"})
        await db.rollback()  # відкат – події не буде
    await asyncio.sleep(0.05)
    assert sent == []
    async with SessionLocal() as db:
        hub_module.publish_after_commit(db, 1, {"type": "y"})
        await db.commit()
    await asyncio.sleep(0.05)
    assert sent == [(1, {"type": "y"})]


async def test_ping_pong(live, client, user_factory):
    ws = await connect(live, await user_factory())
    try:
        await ws.send("ping")
        assert await asyncio.wait_for(ws.recv(), 2) == "pong"
    finally:
        await ws.close()
