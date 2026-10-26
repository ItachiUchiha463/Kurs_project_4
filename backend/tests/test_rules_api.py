from app.config import settings
from tests.test_incidents import incidents, push, server

RULE = {"name": "Мій диск", "cause": "Моя причина", "recommendation": "Зробіть це", "applies_to": ["server"],
        "conditions": [{"scope": "self", "metric": "disk_usage", "op": ">", "value": 90, "instance": "any"}]}


async def disk_incident(client, h, srv):
    await push(client, srv["agent_token"], "disk_usage", 97, ago_s=70, instance="/")
    await push(client, srv["agent_token"], "disk_usage", 97, instance="/")
    [inc] = await incidents(client, h, status="active")
    return (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()


async def test_base_rules_are_listed_as_enabled_and_not_own(client, user_factory):
    h = await user_factory()
    rules = (await client.get("/api/rules", headers=h)).json()
    assert len(rules) > 20 and all(r["enabled"] and not r["own"] for r in rules)


async def test_create_update_delete_own_rule(client, user_factory):
    h = await user_factory()
    r = await client.post("/api/rules", json=RULE, headers=h)
    assert r.status_code == 201 and r.json()["own"] and r.headers["location"] == f"/api/rules/{r.json()['id']}"
    rid = r.json()["id"]
    upd = await client.patch(f"/api/rules/{rid}", json={**RULE, "cause": "Нова причина", "priority": 50}, headers=h)
    assert upd.status_code == 200 and upd.json()["cause"] == "Нова причина" and upd.json()["priority"] == 50
    assert (await client.delete(f"/api/rules/{rid}", headers=h)).status_code == 204
    assert rid not in [x["id"] for x in (await client.get("/api/rules", headers=h)).json()]


async def test_invalid_rules_are_rejected(client, user_factory):
    h = await user_factory()
    cond = RULE["conditions"][0]
    bad = [
        {**RULE, "conditions": [{**cond, "metric": "nope"}]},  # невідома метрика
        {**RULE, "conditions": [{**cond, "scope": "host"}]},  # перша умова не про сам об'єкт
        {**RULE, "conditions": [{**cond, "metric": "db_tps"}]},  # для метрики немає порога: правило ніколи б не розглядалося
        {**RULE, "conditions": [cond, {"scope": "siblings", "metric": "db_up", "op": "==", "value": 0}]},  # сусіди без типу
        {**RULE, "conditions": [{**cond, "agg": "avg"}]},  # агрегація без вікна
        {**RULE, "conditions": [{**cond, "op": "!="}]},
        {**RULE, "conditions": []},
        {**RULE, "applies_to": []},
        {**RULE, "applies_to": ["router"]},
        {**RULE, "name": ""},
    ]
    for body in bad:
        assert (await client.post("/api/rules", json=body, headers=h)).status_code == 422, body


async def test_own_rule_quota(client, user_factory, monkeypatch):
    monkeypatch.setattr(settings, "quota_rules", 1)
    h = await user_factory()
    assert (await client.post("/api/rules", json=RULE, headers=h)).status_code == 201
    assert (await client.post("/api/rules", json=RULE, headers=h)).status_code == 409


async def test_base_rules_cannot_be_edited_only_switched(client, user_factory):
    h = await user_factory()
    base = (await client.get("/api/rules", headers=h)).json()[0]
    assert (await client.patch(f"/api/rules/{base['id']}", json=RULE, headers=h)).status_code == 404
    assert (await client.delete(f"/api/rules/{base['id']}", headers=h)).status_code == 404
    off = await client.put(f"/api/rules/{base['id']}/enabled", json={"enabled": False}, headers=h)
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert next(r for r in (await client.get("/api/rules", headers=h)).json() if r["id"] == base["id"])["enabled"] is False


async def test_disabling_a_base_rule_affects_only_that_user(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    disk = next(r for r in (await client.get("/api/rules", headers=a)).json() if r["name"] == "Заповнення диска")
    await client.put(f"/api/rules/{disk['id']}/enabled", json={"enabled": False}, headers=a)
    da = await disk_incident(client, a, await server(client, a))
    db = await disk_incident(client, b, await server(client, b))
    assert da["diagnosis"]["cause"] == "Причину не визначено"
    assert db["diagnosis"]["cause"] == "Заповнення диска"
    await client.put(f"/api/rules/{disk['id']}/enabled", json={"enabled": True}, headers=a)  # знову ввімкнено


async def test_own_rule_outranks_base_rule_with_the_same_number_of_conditions(client, user_factory):
    h = await user_factory()
    await client.post("/api/rules", json=RULE, headers=h)
    d = await disk_incident(client, h, await server(client, h))
    assert d["diagnosis"]["cause"] == "Моя причина"


async def test_disabled_own_rule_is_ignored(client, user_factory):
    h = await user_factory()
    rid = (await client.post("/api/rules", json=RULE, headers=h)).json()["id"]
    await client.put(f"/api/rules/{rid}/enabled", json={"enabled": False}, headers=h)
    d = await disk_incident(client, h, await server(client, h))
    assert d["diagnosis"]["cause"] == "Заповнення диска"  # власне вимкнене – діє базове


async def test_rule_test_endpoint_explains_each_condition(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    await push(client, srv["agent_token"], "disk_usage", 97, instance="/")
    rid = (await client.post("/api/rules", json=RULE, headers=h)).json()["id"]
    ok = (await client.post(f"/api/rules/{rid}/test", params={"target_id": srv["id"]}, headers=h)).json()
    assert ok["matched"] is True and ok["ratio"] == 1.0 and ok["evidence"][0]["ok"] is True
    two = {**RULE, "conditions": RULE["conditions"] + [{"scope": "self", "metric": "cpu_usage", "op": ">", "value": 90, "agg": "avg", "window_s": 300}]}
    rid2 = (await client.post("/api/rules", json=two, headers=h)).json()["id"]
    partial = (await client.post(f"/api/rules/{rid2}/test", params={"target_id": srv["id"]}, headers=h)).json()
    assert partial["matched"] is False and partial["ratio"] == 0.5 and [e["ok"] for e in partial["evidence"]] == [True, False]


async def test_rule_test_checks_object_type_and_ownership(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    srv = await server(client, a)
    svc = (await client.post("/api/targets", json={"name": "shop", "type": "service", "address": "https://shop.example.ua"}, headers=a)).json()
    rid = (await client.post("/api/rules", json=RULE, headers=a)).json()["id"]
    assert (await client.post(f"/api/rules/{rid}/test", params={"target_id": svc["id"]}, headers=a)).status_code == 422  # правило лише для серверів
    assert (await client.post(f"/api/rules/{rid}/test", params={"target_id": srv["id"]}, headers=b)).status_code == 404
    assert (await client.post(f"/api/rules/{rid}/test", params={"target_id": 99999}, headers=a)).status_code == 404
