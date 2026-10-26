from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal
from app.notify.policy import should_notify
from app.services import checks, pipeline
from tests.test_background import DOWN, age_breach, ping_agent, service, two_failed_checks
from tests.test_incidents import incidents, server


async def server_goes_down(client, srv):
    """Агент мовчить довше за 3 інтервали: інцидент agent_alive."""
    await ping_agent(client, srv)
    async with SessionLocal() as db:
        await checks.check_agents(db, datetime.now(timezone.utc) + timedelta(seconds=120))
        await db.commit()


async def server_returns(client, srv):
    await ping_agent(client, srv)


async def all_incidents(client, h, **params):
    r = await client.get("/api/incidents", params=params, headers=h)
    assert r.status_code == 200
    return r.json()


async def setup(client, user_factory):
    h = await user_factory()
    srv = await server(client, h, "web-01", interval=15)
    svc = await service(client, h, host_id=srv["id"])
    return h, srv, svc


async def test_child_incident_is_suppressed_while_server_is_down(client, user_factory):
    h, srv, svc = await setup(client, user_factory)
    await server_goes_down(client, srv)
    await two_failed_checks(svc["id"])
    opened = await incidents(client, h)
    assert [i["metric"] for i in opened] == ["agent_alive"]  # у списку лише інцидент сервера
    assert opened[0]["suppressed_count"] == 1
    suppressed = await all_incidents(client, h, status="suppressed")
    assert len(suppressed) == 1 and suppressed[0]["target_name"] == "shop" and suppressed[0]["suppressed_by"] == opened[0]["id"]
    assert (await client.get(f"/api/targets/{svc['id']}", headers=h)).json()["status"] == "unavailable"
    detail = (await client.get(f"/api/incidents/{opened[0]['id']}", headers=h)).json()
    assert [r["target_name"] for r in detail["related"]] == ["shop"]


async def test_already_open_child_incident_is_suppressed_when_server_goes_down(client, user_factory):
    h, srv, svc = await setup(client, user_factory)
    await ping_agent(client, srv)
    await two_failed_checks(svc["id"])
    assert [i["metric"] for i in await incidents(client, h)] == ["available"]
    await server_goes_down(client, srv)
    assert [i["metric"] for i in await incidents(client, h)] == ["agent_alive"]
    assert len(await all_incidents(client, h, status="suppressed")) == 1


async def test_recovery_releases_children_and_they_are_evaluated_again(client, user_factory):
    h, srv, svc = await setup(client, user_factory)
    await server_goes_down(client, srv)
    await two_failed_checks(svc["id"])
    await server_returns(client, srv)
    assert await incidents(client, h, status="active") == []
    assert await all_incidents(client, h, status="suppressed") == []
    resolved = await all_incidents(client, h, status="resolved")
    assert {i["metric"] for i in resolved} == {"agent_alive", "available"}  # сервер і придушений сервіс
    # сервіс і далі не працює: після звільнення відкривається вже звичайний інцидент зі своїм сповіщенням
    await two_failed_checks(svc["id"])
    opened = await incidents(client, h, status="active")
    assert [i["metric"] for i in opened] == ["available"] and opened[0]["status"] == "open"


async def test_child_of_healthy_server_opens_normally(client, user_factory):
    h, srv, svc = await setup(client, user_factory)
    await ping_agent(client, srv)
    await two_failed_checks(svc["id"])
    [inc] = await incidents(client, h)
    assert inc["status"] == "open" and inc["suppressed_by"] is None


async def test_manual_close_of_server_incident_releases_children(client, user_factory):
    h, srv, svc = await setup(client, user_factory)
    await server_goes_down(client, srv)
    await two_failed_checks(svc["id"])
    [server_inc] = await incidents(client, h)
    r = await client.post(f"/api/incidents/{server_inc['id']}/resolve", json={"comment": "перезапустив"}, headers=h)
    assert r.status_code == 200
    assert await all_incidents(client, h, status="suppressed") == []


def test_suppressed_changes_are_never_notified():
    for severity in ("warning", "critical"):
        assert not should_notify(chat_id=1, min_severity="warning", kind="suppressed", severity=severity, had_open_notification=False)
