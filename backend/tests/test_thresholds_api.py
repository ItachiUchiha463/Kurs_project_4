from app.notify import messages
from tests.test_incidents import incidents, push, server


async def put(client, h, **body):
    return await client.put("/api/thresholds", json={"duration_s": 0, **body}, headers=h)


async def effective(client, h, metric, target_id=None):
    rows = (await client.get("/api/thresholds", params={"target_id": target_id} if target_id else {}, headers=h)).json()
    return next(r for r in rows if r["metric"] == metric)


async def test_defaults_are_listed_with_their_source(client, user_factory):
    h = await user_factory()
    cpu = await effective(client, h, "cpu_usage")
    assert (cpu["warn"], cpu["crit"], cpu["source"], cpu["levels_editable"]) == (80, 95, "default", True)
    assert (await effective(client, h, "available"))["levels_editable"] is False


async def test_template_threshold_changes_when_an_incident_opens(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv["agent_token"], "cpu_usage", 70, ago_s=300)
    assert await incidents(client, h, status="active") == []  # типово 70 % – ще норма
    assert (await put(client, h, metric="cpu_usage", warn=50, crit=60)).status_code == 204
    await push(client, srv["agent_token"], "cpu_usage", 70)
    [inc] = await incidents(client, h, status="active")
    assert inc["metric"] == "cpu_usage" and inc["severity"] == "critical"  # змінено без перезапуску: кеш скинуто


async def test_target_threshold_beats_template_and_reset_returns_to_default(client, user_factory):
    h = await user_factory()
    a = await server(client, h, "web-01")
    b = await server(client, h, "web-02")
    await put(client, h, metric="cpu_usage", warn=50, crit=60)  # шаблон для всіх
    await put(client, h, metric="cpu_usage", target_id=a["id"], warn=90, crit=99)  # а web-01 – суворіше за шаблон
    assert (await effective(client, h, "cpu_usage", a["id"]))["source"] == "target"
    assert (await effective(client, h, "cpu_usage", b["id"]))["source"] == "template"
    await client.post("/api/ingest", json=[{"host": "web-01", "metric": "cpu_usage", "value": 70, "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}],
                      headers={"Authorization": f"Bearer {a['agent_token']}"})
    assert await incidents(client, h, status="active") == []  # web-01: поріг 90, 70 – норма
    assert (await client.delete("/api/thresholds", params={"metric": "cpu_usage", "target_id": a["id"]}, headers=h)).status_code == 204
    assert (await effective(client, h, "cpu_usage", a["id"]))["source"] == "template"
    assert (await client.delete("/api/thresholds", params={"metric": "cpu_usage"}, headers=h)).status_code == 204
    assert (await effective(client, h, "cpu_usage"))["source"] == "default"
    assert (await client.delete("/api/thresholds", params={"metric": "cpu_usage"}, headers=h)).status_code == 404


async def test_invalid_thresholds_are_rejected(client, user_factory):
    h = await user_factory()
    assert (await put(client, h, metric="cpu_usage", warn=90, crit=80)).status_code == 422  # попередження вище за критичний
    assert (await put(client, h, metric="cpu_usage")).status_code == 422  # жодного рівня
    assert (await put(client, h, metric="db_cache_hit_pct", warn=85, crit=90)).status_code == 422  # «нижче за»: warn має бути більшим
    assert (await put(client, h, metric="db_cache_hit_pct", warn=95, crit=90)).status_code == 204
    assert (await put(client, h, metric="available", crit=1)).status_code == 422  # бінарна: лише тривалість
    assert (await put(client, h, metric="available", duration_s=60)).status_code == 204
    assert (await put(client, h, metric="nope", warn=1)).status_code == 422
    assert (await put(client, h, metric="cpu_usage", warn=50, crit=60, duration_s=4000)).status_code == 422
    assert (await put(client, h, metric="cpu_usage", warn=-1, crit=60)).status_code == 422


async def test_thresholds_are_private_to_their_owner(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    srv = await server(client, a)
    await put(client, a, metric="cpu_usage", warn=10, crit=20)
    assert (await effective(client, b, "cpu_usage"))["source"] == "default"  # чужий шаблон не діє
    assert (await put(client, b, metric="cpu_usage", target_id=srv["id"], warn=1, crit=2)).status_code == 404
    assert (await client.get("/api/thresholds", params={"target_id": srv["id"]}, headers=b)).status_code == 404
    assert (await client.get("/api/thresholds")).status_code == 401


def test_alert_text_shows_the_effective_limit():
    assert "(поріг 60 %)" in messages.threshold_text("cpu_usage", "critical", 60)
    assert "(поріг 95 %)" in messages.threshold_text("cpu_usage", "critical")
