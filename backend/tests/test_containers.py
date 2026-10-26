from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Target
from app.services import checks, ingest
from tests.test_background import ping_agent
from tests.test_incidents import incidents, server
from tests.test_targets import rec

CID = "3f2a9c"
INFO = {"id": CID, "name": "web", "image": "nginx:1.27", "state": "running"}


def now():
    return datetime.now(timezone.utc)


async def push_child(client, srv, metric, value, ago_s=0, cid=CID, containers=(INFO,)):
    body = {"records": [rec(metric, value, host=srv["name"], ts=now() - timedelta(seconds=ago_s), target=f"docker:{cid}")],
            "containers": list(containers)}
    r = await client.post("/api/ingest", json=body, headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert r.status_code == 200, r.text
    return r.json()


async def children(db, server_id):
    return list(await db.scalars(select(Target).where(Target.host_id == server_id)))


async def test_container_is_discovered_once_and_gets_its_metrics(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    for _ in range(2):
        out = await push_child(client, srv, "container_cpu", 12.5)
        assert out["accepted"] == 1 and out["rejected"] == []
    async with SessionLocal() as db:
        [child] = await children(db, srv["id"])
        assert (child.type, child.name, child.source, child.check_type, child.external_id) == ("container", "web", "discovered", "docker", CID)
        assert child.address == "nginx:1.27" and child.last_seen is not None
    got = (await client.get(f"/api/targets/{child.id}", headers=h)).json()
    assert got["latest"]["container_cpu"] == 12.5 and got["host_id"] == srv["id"]


async def test_unknown_child_is_rejected_and_old_list_format_still_works(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    out = await push_child(client, srv, "container_cpu", 5, cid="nope", containers=())
    assert [x["reason"] for x in out["rejected"]] == ["невідомий дочірній об'єкт сервера"]
    r = await client.post("/api/ingest", json=[rec("cpu_usage", 10)], headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert r.status_code == 200 and r.json()["accepted"] == 1


async def test_hidden_container_is_not_monitored(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_cpu", 5)
    async with SessionLocal() as db:
        [child] = await children(db, srv["id"])
        child.hidden = True
        await db.commit()
    out = await push_child(client, srv, "container_running", 0)
    assert out == {"accepted": 0, "rejected": []}
    assert child.id not in [t["id"] for t in (await client.get("/api/targets", headers=h)).json()]


async def test_discovered_containers_do_not_use_the_user_quota(client, user_factory, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "quota_targets", 1)
    h = await user_factory()
    srv = await server(client, h)
    many = [{"id": f"c{i}", "name": f"app-{i}", "image": "x", "state": "running"} for i in range(5)]
    await push_child(client, srv, "container_cpu", 1, cid="c0", containers=many)
    async with SessionLocal() as db:
        assert len(await children(db, srv["id"])) == 5
    # лімітом квоти лишається лише 1 об'єкт, який користувач створив сам
    assert (await client.post("/api/targets", json={"name": "b", "type": "server"}, headers=h)).status_code == 409


async def test_gone_container_is_hidden_after_a_day(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_cpu", 1)
    async with SessionLocal() as db:
        server_row = await db.get(Target, srv["id"])
        await ingest.sync_containers(db, server_row, [], now() + timedelta(hours=1))
        assert not (await children(db, srv["id"]))[0].hidden
        await ingest.sync_containers(db, server_row, [], now() + timedelta(hours=25))
        assert (await children(db, srv["id"]))[0].hidden


async def test_deleting_server_removes_discovered_containers(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_cpu", 1)
    assert (await client.delete(f"/api/targets/{srv['id']}", headers=h)).status_code == 204
    async with SessionLocal() as db:
        assert await db.scalar(select(Target.id).where(Target.external_id == CID)) is None


async def test_stopped_container_opens_incident_with_diagnosis(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_running", 0, ago_s=40)
    await push_child(client, srv, "container_exit_code", 0, ago_s=40)
    await push_child(client, srv, "container_running", 0)
    [inc] = await incidents(client, h, status="active")
    assert inc["metric"] == "container_running" and inc["severity"] == "critical" and inc["target_name"] == "web"
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert detail["diagnosis"]["cause"].startswith("Контейнер зупинено штатно")
    child = (await client.get("/api/targets", headers=h)).json()
    assert [t["status"] for t in child if t["type"] == "container"] == ["unavailable"]


async def test_oom_killed_container_gets_oom_diagnosis(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_running", 0, ago_s=40)
    await push_child(client, srv, "container_oom_killed", 1)
    await push_child(client, srv, "container_running", 0)
    inc = next(i for i in await incidents(client, h, status="active") if i["metric"] == "container_oom_killed")
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert "нестачу пам'яті" in detail["diagnosis"]["cause"]


async def test_restart_counter_growth_opens_incident(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push_child(client, srv, "container_restarts", 2, ago_s=300)
    await push_child(client, srv, "container_restarts", 6)  # +4 за вікно: ≥ 3 перезапусків
    inc = next(i for i in await incidents(client, h, status="active") if i["metric"] == "container_restarts")
    assert inc["severity"] == "critical"


async def test_container_incident_is_suppressed_while_server_does_not_answer_ping(client, user_factory):
    from app.checks.http import CheckResult
    from app.services import pipeline
    from tests.test_net_checks import make_pinged_server, run_ping
    h = await user_factory()
    srv = await make_pinged_server(client, h)
    down = CheckResult(0, None, packet_loss=100.0)
    await run_ping(srv["id"], down)
    key = (srv["id"], "ping_available", "")
    st = pipeline._states[key]
    pipeline._states[key] = type(st)(breach_since=st.breach_since - timedelta(seconds=31))
    await run_ping(srv["id"], down)
    await push_child(client, srv, "container_running", 0, ago_s=40)
    await push_child(client, srv, "container_running", 0)
    assert [i["metric"] for i in await incidents(client, h, status="active")] == ["ping_available"]
    [hidden] = await incidents(client, h, status="suppressed")
    assert hidden["target_name"] == "web" and hidden["metric"] == "container_running"


async def test_children_listing_and_hiding(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    other = await user_factory(email="b@example.com")
    await push_child(client, srv, "container_cpu", 5)
    [kid] = (await client.get(f"/api/targets/{srv['id']}/children", headers=h)).json()
    assert kid["name"] == "web" and kid["latest"]["container_cpu"] == 5
    assert (await client.get(f"/api/targets/{srv['id']}/children", headers=other)).status_code == 404  # чужий сервер
    hidden = await client.put(f"/api/targets/{kid['id']}/hidden", json={"hidden": True}, headers=h)
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    assert kid["id"] not in [t["id"] for t in (await client.get("/api/targets", headers=h)).json()]
    assert (await client.get(f"/api/targets/{srv['id']}/children", headers=h)).json()[0]["hidden"] is True  # у списку дочірніх лишається
    assert (await client.put(f"/api/targets/{srv['id']}/hidden", json={"hidden": True}, headers=h)).status_code == 422  # лише виявлені
