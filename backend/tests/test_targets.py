from datetime import datetime, timedelta, timezone

from tests.helpers import now as NOW  # noqa: E402


def rec(metric="cpu_usage", value=50.0, host="web-01", ts=None, **kw):
    return {"host": host, "metric": metric, "value": value, "timestamp": (ts or NOW()).isoformat(), **kw}


async def make_server(client, h, name="web-01"):
    r = await client.post("/api/targets", json={"name": name, "type": "server"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_server_gets_token_once_and_response_hides_hash(client, user_factory):
    h = await user_factory()
    created = await make_server(client, h)
    assert created["agent_token"].startswith("vgl_")
    assert "agent_token_hash" not in created
    listed = (await client.get("/api/targets", headers=h)).json()
    assert "agent_token" not in listed[0] and "agent_token_hash" not in listed[0]


async def test_service_needs_http_address(client, user_factory):
    h = await user_factory()
    r = await client.post("/api/targets", json={"name": "shop", "type": "service", "address": "shop.example.ua"}, headers=h)
    assert r.status_code == 422
    r = await client.post("/api/targets", json={"name": "shop", "type": "service", "address": "https://shop.example.ua"}, headers=h)
    assert r.status_code == 201 and r.json()["check_type"] == "http"


async def test_quota(client, user_factory, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "quota_targets", 1)
    h = await user_factory()
    await make_server(client, h, "a")
    r = await client.post("/api/targets", json={"name": "b", "type": "server"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "quota_exceeded"


async def test_ingest_stores_and_shows_latest(client, user_factory):
    h = await user_factory()
    t = await make_server(client, h)
    r = await client.post("/api/ingest", json=[rec("cpu_usage", 42.5), rec("disk_usage", 71, instance="/")],
                          headers={"Authorization": f"Bearer {t['agent_token']}", "X-Agent-Version": "0.1"})
    assert r.status_code == 200 and r.json() == {"accepted": 2, "rejected": []}
    got = (await client.get(f"/api/targets/{t['id']}", headers=h)).json()
    assert got["latest"] == {"cpu_usage": 42.5, "disk_usage:/": 71, "agent_alive": 1}
    assert got["last_seen"] and got["agent_version"] == "0.1"


async def test_ingest_rejects_bad_records_but_keeps_good(client, user_factory):
    h = await user_factory()
    t = await make_server(client, h)
    batch = [rec("cpu_usage", 10), rec("cpu_usage", 150), rec("bogus_metric", 1), rec("cpu_usage", 1, host="other"),
             rec("cpu_usage", 1, ts=NOW() + timedelta(minutes=10)), rec("cpu_usage", 1, ts=NOW() - timedelta(hours=2)),
             rec("cpu_usage", 1, target="docker:abc"), rec("cpu_usage", -5)]
    r = await client.post("/api/ingest", json=batch, headers={"Authorization": f"Bearer {t['agent_token']}"})
    body = r.json()
    assert body["accepted"] == 1
    assert [x["index"] for x in body["rejected"]] == [1, 2, 3, 4, 5, 6, 7]


async def test_ingest_requires_valid_token(client, user_factory):
    assert (await client.post("/api/ingest", json=[rec()])).status_code == 401
    assert (await client.post("/api/ingest", json=[rec()], headers={"Authorization": "Bearer vgl_nope"})).status_code == 401


async def test_ingest_corrects_agent_clock(client, user_factory):
    h = await user_factory()
    t = await make_server(client, h)
    agent_now = NOW() - timedelta(minutes=30)  # годинник агента відстає на 30 хв
    r = await client.post("/api/ingest", json=[rec(ts=agent_now)],
                          headers={"Authorization": f"Bearer {t['agent_token']}", "X-Agent-Time": agent_now.isoformat()})
    assert r.json()["accepted"] == 1
    got = (await client.get(f"/api/targets/{t['id']}", headers=h)).json()
    assert 1790 < got["clock_offset_s"] < 1810
    # без виправлення запис був би старший за 15 хв і не потрапив би в «останні значення»
    assert got["latest"]["cpu_usage"] == 50.0


async def test_old_token_stops_working_after_rotation(client, user_factory):
    h = await user_factory()
    t = await make_server(client, h)
    new = (await client.post(f"/api/targets/{t['id']}/agent-token", headers=h)).json()["agent_token"]
    old = await client.post("/api/ingest", json=[rec()], headers={"Authorization": f"Bearer {t['agent_token']}"})
    ok = await client.post("/api/ingest", json=[rec()], headers={"Authorization": f"Bearer {new}"})
    assert old.status_code == 401 and ok.status_code == 200


async def test_metric_series(client, user_factory):
    h = await user_factory()
    t = await make_server(client, h)
    now = NOW()
    await client.post("/api/ingest", json=[rec(value=v, ts=now - timedelta(seconds=30 * i)) for i, v in enumerate([10, 20, 30])],
                      headers={"Authorization": f"Bearer {t['agent_token']}"})
    pts = (await client.get(f"/api/targets/{t['id']}/metrics", params={"name": "cpu_usage"}, headers=h)).json()
    assert sorted(p["value"] for p in pts)[-1] >= 10 and len(pts) >= 1


async def test_ingest_rate_limit(client, user_factory, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ingest_min_interval_s", 60)
    h = await user_factory()
    t = await make_server(client, h)
    hh = {"Authorization": f"Bearer {t['agent_token']}"}
    assert (await client.post("/api/ingest", json=[rec()], headers=hh)).status_code == 200
    assert (await client.post("/api/ingest", json=[rec()], headers=hh)).status_code == 429
