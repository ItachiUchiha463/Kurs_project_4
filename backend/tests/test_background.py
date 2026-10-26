import asyncio
from datetime import datetime, timedelta, timezone

from app import background
from app.checks.http import CheckResult
from app.db import SessionLocal
from app.services import checks, pipeline
from tests.test_incidents import incidents, server
from tests.test_targets import rec

DOWN = CheckResult(0, None, 0, "ConnectError")


async def service(client, h, host_id=None, interval=15):
    body = {"name": "shop", "type": "service", "address": "https://shop.example.ua", "interval_s": interval}
    if host_id:
        body["host_id"] = host_id
    r = await client.post("/api/targets", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def run_check(target_id, result):
    from app.models import Target

    async def fake(url, expected):
        return result

    async with SessionLocal() as db:
        await checks.run_check(db, await db.get(Target, target_id), fake)
        await db.commit()


def age_breach(target_id, seconds=31):
    """Зсуває початок порушення в минуле: імітує, що з першої невдалої перевірки минуло `seconds`."""
    key = (target_id, "available", "")
    st = pipeline._states[key]
    pipeline._states[key] = type(st)(breach_since=st.breach_since - timedelta(seconds=seconds))


async def two_failed_checks(target_id, result=DOWN):
    await run_check(target_id, result)
    age_breach(target_id)
    await run_check(target_id, result)


async def ping_agent(client, srv, cpu=10):
    r = await client.post("/api/ingest", json=[rec("cpu_usage", cpu, host=srv["name"])],
                          headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert r.status_code == 200, r.text


async def test_service_creation_rejects_private_address(client, user_factory, monkeypatch):
    from app.checks import ssrf
    monkeypatch.setattr("app.services.targets.address_resolver", ssrf.resolve_public)
    h = await user_factory()
    for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://10.0.0.5:8080/admin", "http://localhost/"):
        r = await client.post("/api/targets", json={"name": "x", "type": "service", "address": url}, headers=h)
        assert r.status_code == 422, url
        assert r.json()["error"]["details"][0]["field"] == "address"


async def test_failed_checks_open_incident_after_thirty_seconds_and_resolve(client, user_factory):
    h = await user_factory()
    s = await service(client, h)
    await run_check(s["id"], DOWN)
    assert await incidents(client, h) == []  # перша невдача ще не інцидент
    age_breach(s["id"])
    await run_check(s["id"], DOWN)
    [inc] = await incidents(client, h)
    assert inc["metric"] == "available" and inc["severity"] == "critical"
    assert (await client.get(f"/api/targets/{s['id']}", headers=h)).json()["status"] == "unavailable"
    up = CheckResult(1, 120.0, 200)
    await run_check(s["id"], up)
    assert (await incidents(client, h))[0]["status"] == "open"  # закриття – лише після 30 с стабільної роботи
    key = (s["id"], "available", "")
    st = pipeline._states[key]
    pipeline._states[key] = type(st)(incident=st.incident, calm_since=st.calm_since - timedelta(seconds=31))
    await run_check(s["id"], up)
    assert (await incidents(client, h))[0]["status"] == "resolved"
    assert (await client.get(f"/api/targets/{s['id']}", headers=h)).json()["status"] == "ok"


async def test_stopped_service_on_live_server_is_diagnosed(client, user_factory):
    """Правило 5: сервіс мовчить, а сервер із агентом працює."""
    h = await user_factory()
    srv = await server(client, h, "demo-1")
    await ping_agent(client, srv)
    s = await service(client, h, host_id=srv["id"])
    await two_failed_checks(s["id"])
    [inc] = await incidents(client, h)
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"] == "Сервіс зупинено, сам сервер працює"
    assert [e["ok"] for e in d["evidence"]] == [True, True]


async def test_http_500_with_calm_cpu_is_application_error(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "demo-1")
    await ping_agent(client, srv, cpu=20)
    s = await service(client, h, host_id=srv["id"])
    await two_failed_checks(s["id"], CheckResult(0, 80.0, 500))
    [inc] = await incidents(client, h)
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"] == "Помилка в застосунку"  # конкретніше (3 умови) за «сервіс зупинено» (2 умови)


async def test_silent_agent_is_marked_dead_and_revives(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "demo-1", interval=15)
    await ping_agent(client, srv)
    future = datetime.now(timezone.utc) + timedelta(seconds=60)  # понад 3 інтервали мовчання
    async with SessionLocal() as db:
        assert await checks.check_agents(db, future) == 1
        await db.commit()
    [inc] = await incidents(client, h)
    assert inc["metric"] == "agent_alive" and inc["severity"] == "critical"
    assert (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()["status"] == "unavailable"
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"].startswith("Сервер вимкнений")
    await ping_agent(client, srv)  # агент повернувся
    assert (await incidents(client, h))[0]["status"] == "resolved"
    assert (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()["status"] == "ok"


async def test_live_agent_is_not_marked_dead(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "demo-1", interval=15)
    await ping_agent(client, srv)
    async with SessionLocal() as db:
        assert await checks.check_agents(db) == 0


async def test_schedule_due_respects_interval_and_runs_each_check_once(client, user_factory):
    h = await user_factory()
    s = await service(client, h, interval=30)
    background._next_run.clear()
    background._running.clear()
    calls = []

    async def fake(url, expected):
        calls.append(url)
        return CheckResult(1, 50.0, 200)

    assert await background.schedule_due(fake, now=1000.0) == 1
    await asyncio.sleep(0.5)
    assert await background.schedule_due(fake, now=1010.0) == 0  # інтервал 30 с ще не минув
    assert await background.schedule_due(fake, now=1031.0) == 1
    await asyncio.sleep(0.5)
    assert len(calls) == 2
    got = (await client.get(f"/api/targets/{s['id']}", headers=h)).json()
    assert got["latest"]["available"] == 1 and got["status"] == "ok"


async def test_second_process_does_not_get_background_lock():
    first, second, third = background.Background(), background.Background(), background.Background()
    try:
        assert await first.start() is True
        assert await second.start() is False  # lock уже тримає перший процес
    finally:
        await first.stop()
        await second.stop()
    try:
        assert await third.start() is True  # після зупинки першого lock вільний
    finally:
        await third.stop()


async def test_health(client, monkeypatch):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["db"] == "ok"
    monkeypatch.setattr(background, "started", True)
    monkeypatch.setattr(background, "beats", {"scheduler": 0.0})
    assert background.health(now=1000.0)["ok"] is False
    assert background.health(now=60.0)["ok"] is True
