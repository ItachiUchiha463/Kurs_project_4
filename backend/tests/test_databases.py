from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Target
from tests.test_containers import INFO as CONTAINER
from tests.test_incidents import incidents, server
from tests.test_targets import rec

DB = {"id": "orders", "name": "orders-db", "engine": "postgres"}


def now():
    return datetime.now(timezone.utc)


async def push(client, srv, records, containers=(), databases=(DB,)):
    body = {"records": [rec(m, v, host=srv["name"], ts=now() - timedelta(seconds=ago), target=t) for m, v, ago, t in records],
            "containers": list(containers), "databases": list(databases)}
    r = await client.post("/api/ingest", json=body, headers={"Authorization": f"Bearer {srv['agent_token']}"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_database_is_discovered_and_gets_metrics(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    out = await push(client, srv, [("db_response_ms", 3.5, 0, "postgres:orders"), ("db_connections_pct", 40, 0, "postgres:orders")])
    assert out == {"accepted": 2, "rejected": []}
    async with SessionLocal() as db:
        child = await db.scalar(select(Target).where(Target.host_id == srv["id"], Target.type == "database"))
    assert (child.name, child.check_type, child.source, child.external_id) == ("orders-db", "postgres", "discovered", "postgres:orders")
    got = (await client.get(f"/api/targets/{child.id}", headers=h)).json()
    assert got["latest"]["db_connections_pct"] == 40


async def test_percent_metric_out_of_range_is_rejected(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    out = await push(client, srv, [("db_cache_hit_pct", 140, 0, "postgres:orders"), ("db_up", 1, 0, "postgres:orders")])
    assert out["accepted"] == 1 and out["rejected"][0]["reason"] == "значення поза допустимим діапазоном"


async def test_database_down_while_its_container_is_stopped_gets_container_diagnosis(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    stopped = [("container_running", 0, 0, f"docker:{CONTAINER['id']}")]
    await push(client, srv, [("db_up", 0, 40, "postgres:orders")] + stopped, containers=[CONTAINER])
    await push(client, srv, [("db_up", 0, 0, "postgres:orders")] + stopped, containers=[CONTAINER])
    inc = next(i for i in await incidents(client, h, status="active") if i["metric"] == "db_up")
    assert inc["target_name"] == "orders-db" and inc["severity"] == "critical"
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert "зупинився її контейнер" in detail["diagnosis"]["cause"]
    assert any("сусідніх" in e["text"] or "сервері" in e["text"] for e in detail["diagnosis"]["evidence"])


async def test_exhausted_connection_pool_diagnosis(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    both = lambda ago: [("db_connections_pct", 97, ago, "postgres:orders"), ("db_idle_in_tx", 25, ago, "postgres:orders")]  # noqa: E731
    await push(client, srv, both(70))
    await push(client, srv, both(0))
    inc = next(i for i in await incidents(client, h, status="active") if i["metric"] == "db_connections_pct")
    assert inc["severity"] == "critical"
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert detail["diagnosis"]["cause"].startswith("Вичерпано пул з'єднань")


async def test_low_cache_hit_ratio_uses_below_direction(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv, [("db_cache_hit_pct", 85, 0, "postgres:orders")])
    inc = next(i for i in await incidents(client, h, status="active") if i["metric"] == "db_cache_hit_pct")
    assert inc["severity"] == "critical"  # < 90 %
