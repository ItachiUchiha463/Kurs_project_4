"""Ізоляція користувачів (ТЗ розд. 15): чужий ресурс – 404, а не 403 чи дані."""
import re

import pytest

from tests.test_targets import make_server, rec

# Кожен шлях із параметром ресурсу має бути тут, інакше test_every_resource_route_is_covered падає.
OWNED = [
    ("GET", "/api/targets/{target_id}", None),
    ("DELETE", "/api/targets/{target_id}", None),
    ("POST", "/api/targets/{target_id}/agent-token", None),
    ("GET", "/api/targets/{target_id}/metrics?name=cpu_usage", None),
    ("GET", "/api/targets/{target_id}/children", None),
    ("PUT", "/api/targets/{target_id}/hidden", {"hidden": True}),
    ("GET", "/api/incidents/{incident_id}", None),
    ("POST", "/api/incidents/{incident_id}/acknowledge", None),
    ("POST", "/api/incidents/{incident_id}/resolve", {"comment": "x"}),
]
PUBLIC_WITH_PARAMS: set[str] = set()
RULE_BODY = {"name": "Моє", "cause": "Причина", "recommendation": "Зробіть це", "applies_to": ["server"],
             "conditions": [{"scope": "self", "metric": "cpu_usage", "op": ">", "value": 90}]}
OWNED += [
    ("PATCH", "/api/rules/{rule_id}", RULE_BODY),
    ("DELETE", "/api/rules/{rule_id}", None),
    ("PUT", "/api/rules/{rule_id}/enabled", {"enabled": False}),
    ("POST", "/api/rules/{rule_id}/test?target_id={target_id}", None),
]


async def test_other_users_resources_are_404(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    t = await make_server(client, a)
    await client.post("/api/ingest", json=[rec("cpu_usage", 99)], headers={"Authorization": f"Bearer {t['agent_token']}"})
    [inc] = (await client.get("/api/incidents", headers=a)).json()
    rule_id = (await client.post("/api/rules", json=RULE_BODY, headers=a)).json()["id"]
    for method, path, body in OWNED:
        r = await client.request(method, path.format(target_id=t["id"], incident_id=inc["id"], rule_id=rule_id), json=body, headers=b)
        assert r.status_code == 404, (method, path, r.status_code)
    # а власник усе ще бачить свій об'єкт: чужі спроби нічого не видалили
    assert (await client.get(f"/api/targets/{t['id']}", headers=a)).status_code == 200
    assert (await client.get(f"/api/incidents/{inc['id']}", headers=a)).json()["status"] == "open"
    assert any(r["id"] == rule_id for r in (await client.get("/api/rules", headers=a)).json())  # чуже видалення не спрацювало


async def test_lists_contain_only_own_data(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    await make_server(client, a, "a-server")
    assert (await client.get("/api/targets", headers=b)).json() == []
    assert (await client.get("/api/incidents", headers=b)).json() == []


async def test_agent_token_of_a_cannot_write_metrics_of_b(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    ta = await make_server(client, a, "web-01")
    tb = await make_server(client, b, "web-01")
    r = await client.post("/api/ingest", json=[rec(host="web-01", value=99)],
                          headers={"Authorization": f"Bearer {ta['agent_token']}"})
    assert r.json()["accepted"] == 1
    got = (await client.get(f"/api/targets/{tb['id']}", headers=b)).json()
    assert got["latest"] == {}  # метрика потрапила лише до об'єкта власника токена


def test_every_resource_route_is_covered():
    from app.main import app
    covered = {(m, re.sub(r"\?.*", "", p)) for m, p, _ in OWNED}
    missing = []
    for path, ops in app.openapi()["paths"].items():
        if "{" not in path or path in PUBLIC_WITH_PARAMS:
            continue
        for method in ops:
            if (method.upper(), path.replace("/api", "/api", 1)) not in covered:
                missing.append((method.upper(), path))
    assert not missing, f"Ресурс без перевірки ізоляції: {missing}"
