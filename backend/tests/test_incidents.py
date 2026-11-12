from datetime import datetime, timedelta, timezone

from tests.test_targets import rec

from tests.helpers import now as NOW  # noqa: E402


async def server(client, h, name="web-01", interval=3600):
    # довгий інтервал: «свіжими» вважаються записи до 2 год давності, тож у тестах можна керувати часом точок
    r = await client.post("/api/targets", json={"name": name, "type": "server", "interval_s": interval}, headers=h)
    return r.json()


async def push(client, token, metric, value, ago_s=0, instance=""):
    r = await client.post("/api/ingest", json=[rec(metric, value, ts=NOW() - timedelta(seconds=ago_s), instance=instance)],
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


async def incidents(client, h, **params):
    return (await client.get("/api/incidents", params=params, headers=h)).json()


async def test_spike_opens_incident_and_sets_target_status(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 97)
    [inc] = await incidents(client, h)
    assert inc["severity"] == "critical" and inc["status"] == "open" and inc["metric"] == "cpu_usage"
    assert inc["target_name"] == "web-01" and inc["value_at_open"] == 97
    assert (await client.get(f"/api/targets/{t['id']}", headers=h)).json()["status"] == "critical"
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert [e["type"] for e in detail["events"]] == ["detected", "opened"]


async def test_normal_values_keep_target_ok(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 20)
    assert await incidents(client, h) == []
    assert (await client.get(f"/api/targets/{t['id']}", headers=h)).json()["status"] == "ok"


async def test_repeated_breach_does_not_duplicate_incident(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    for ago in (300, 200, 100):
        await push(client, t["agent_token"], "cpu_usage", 98, ago_s=ago)
    assert len(await incidents(client, h)) == 1


async def test_escalation_warning_to_critical(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 85, ago_s=600)
    assert (await incidents(client, h))[0]["severity"] == "warning"
    await push(client, t["agent_token"], "cpu_usage", 99, ago_s=300)
    [inc] = await incidents(client, h)
    assert inc["severity"] == "critical"
    detail = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()
    assert "escalated" in [e["type"] for e in detail["events"]]


async def test_auto_resolve_when_value_returns_to_normal(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 97, ago_s=1000)
    await push(client, t["agent_token"], "cpu_usage", 10, ago_s=500)  # вікно avg 2 хв охоплює лише цю точку
    [inc] = await incidents(client, h)
    assert inc["status"] == "resolved" and inc["resolved_at"]
    assert (await client.get(f"/api/targets/{t['id']}", headers=h)).json()["status"] == "ok"
    assert await incidents(client, h, status="active") == []


async def test_late_buffered_data_is_stored_but_opens_no_incident(client, user_factory):
    h = await user_factory()
    t = await server(client, h, interval=30)
    await push(client, t["agent_token"], "cpu_usage", 99, ago_s=300)  # старше за 2 інтервали
    assert await incidents(client, h) == []
    pts = (await client.get(f"/api/targets/{t['id']}/metrics", params={"name": "cpu_usage"}, headers=h)).json()
    assert pts and pts[0]["value"] == 99


async def test_disk_needs_sixty_seconds_and_instances_are_independent(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "disk_usage", 97, ago_s=200, instance="/")
    assert await incidents(client, h) == []  # duration_s = 60: одна точка ще не інцидент
    await push(client, t["agent_token"], "disk_usage", 97, ago_s=100, instance="/")
    await push(client, t["agent_token"], "disk_usage", 40, ago_s=100, instance="/data")
    [inc] = await incidents(client, h)
    assert inc["instance"] == "/" and inc["severity"] == "critical"


async def test_acknowledge_then_manual_resolve_requires_comment(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 97)
    [inc] = await incidents(client, h)
    r = await client.post(f"/api/incidents/{inc['id']}/acknowledge", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert (await client.post(f"/api/incidents/{inc['id']}/acknowledge", headers=h)).status_code == 409
    assert (await client.post(f"/api/incidents/{inc['id']}/resolve", json={}, headers=h)).status_code == 422
    r = await client.post(f"/api/incidents/{inc['id']}/resolve", json={"comment": "Перезапустив сервіс"}, headers=h)
    assert r.json()["status"] == "resolved" and r.json()["resolve_comment"] == "Перезапустив сервіс"
    assert (await client.post(f"/api/incidents/{inc['id']}/resolve", json={"comment": "ще раз"}, headers=h)).status_code == 409


async def test_state_is_restored_from_db_after_restart(client, user_factory):
    from app.services import pipeline
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 97, ago_s=200)
    pipeline._states.clear()  # імітація перезапуску процесу
    await push(client, t["agent_token"], "cpu_usage", 98, ago_s=100)
    assert len(await incidents(client, h)) == 1


async def test_filters_and_cursor(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 97, ago_s=500)
    await push(client, t["agent_token"], "ram_usage", 90, ago_s=400)
    both = await incidents(client, h)
    assert len(both) == 2 and both[0]["id"] > both[1]["id"]
    assert len(await incidents(client, h, severity="critical")) == 1
    assert len(await incidents(client, h, limit=1)) == 1
    assert len(await incidents(client, h, cursor=both[0]["id"])) == 1


async def test_incident_gets_diagnosis_with_evidence(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "swap_usage", 60, ago_s=200)  # порогів немає, лише факт для правила
    await push(client, t["agent_token"], "ram_usage", 97, ago_s=100)
    [inc] = await incidents(client, h)
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"] == "Нестача оперативної пам'яті" and d["matched_ratio"] == 1.0
    assert d["recommendation"]
    assert [e["ok"] for e in d["evidence"]] == [True, True]
    assert d["evidence"][0]["value"] == "97 % > 90 %" and d["evidence"][1]["value"] == "60 % > 50 %"


async def test_unexplained_incident_says_cause_unknown(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "cpu_usage", 99)
    [inc] = await incidents(client, h)
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"] == "Причину не визначено" and d["evidence"] == []


async def test_user_can_only_link_service_to_own_server(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    sa = await server(client, a)
    body = {"name": "shop", "type": "service", "address": "https://shop.example.ua", "host_id": sa["id"]}
    assert (await client.post("/api/targets", json=body, headers=b)).status_code == 404
    ok = await client.post("/api/targets", json=body, headers=a)
    assert ok.status_code == 201 and ok.json()["host_id"] == sa["id"]


async def test_growing_ram_gets_trend_diagnosis(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    for value, ago in ((60, 3000), (70, 2400), (78, 1800), (84, 1200)):  # ще нижче порогу: інцидент не відкривається
        await push(client, t["agent_token"], "ram_usage", value, ago_s=ago)
    assert await incidents(client, h) == []
    await push(client, t["agent_token"], "ram_usage", 90, ago_s=100)
    [inc] = await incidents(client, h)
    d = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]
    assert d["cause"].startswith("Використання пам'яті стабільно росте")
    assert any("зміна за годину" in e["text"] and e["ok"] and "%/год" in e["value"] for e in d["evidence"])


async def test_diagnosis_context_mentions_reboot_and_earlier_incident(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "uptime_h", 0.1, ago_s=300)  # 6 хв після завантаження
    await push(client, t["agent_token"], "cpu_usage", 97, ago_s=200)
    await push(client, t["agent_token"], "ram_usage", 97, ago_s=100)
    cpu, ram = sorted(await incidents(client, h), key=lambda i: i["id"])
    ctx = (await client.get(f"/api/incidents/{ram['id']}", headers=h)).json()["diagnosis"]["context"]
    assert any("перезавантажено близько 6 хв тому" in c for c in ctx)
    assert any("почався інцидент" in c and "CPU" in c for c in ctx)
    first = (await client.get(f"/api/incidents/{cpu['id']}", headers=h)).json()["diagnosis"]["context"]
    assert not any("почався інцидент" in c for c in first)  # раніше за нього інцидентів не було


async def test_alternatives_show_percent_and_missing_conditions(client, user_factory):
    h = await user_factory()
    t = await server(client, h)
    await push(client, t["agent_token"], "ram_usage", 97, ago_s=100)  # swap невідомий: правило «Нестача RAM» виконано наполовину
    [inc] = await incidents(client, h)
    alts = (await client.get(f"/api/incidents/{inc['id']}", headers=h)).json()["diagnosis"]["alternatives"]
    shortage = next(a for a in alts if a["name"] == "Нестача оперативної пам'яті")
    assert shortage["pct"] == 50 and shortage["ok"] == 1 and shortage["total"] == 2
    assert shortage["missing"] == [{"text": "Swap web-01", "value": "немає даних"}]
