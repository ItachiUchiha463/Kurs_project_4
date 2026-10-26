import asyncio

import pytest

from app import background
from app.checks import net, ssrf
from app.checks.http import CheckResult
from app.db import SessionLocal
from app.models import Target
from app.services import checks, pipeline
from tests.test_background import age_breach
from tests.test_incidents import incidents, server

LINUX = """PING 93.184.216.34 (93.184.216.34) 56(84) bytes of data.
--- 93.184.216.34 ping statistics ---
3 packets transmitted, 2 received, 33.3333% packet loss, time 2003ms
rtt min/avg/max/mdev = 10.100/12.500/14.900/2.400 ms
"""
WINDOWS = """Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 8ms, Maximum = 14ms, Average = 11ms"""


def test_parse_ping_linux_and_windows():
    assert net.parse_ping(LINUX) == (33.3333, 12.5)
    assert net.parse_ping(WINDOWS) == (0.0, 11.0)
    assert net.parse_ping("Request timed out.") == (100.0, None)


@pytest.mark.parametrize("bad", ["example.com", "example.com:0", "example.com:70000", ":80", "example.com:ab"])
def test_tcp_address_needs_valid_port(bad):
    with pytest.raises(ValueError):
        net.split_host_port(bad)


async def public(host, port):
    return "93.184.216.34"


async def blocked(host, port):
    raise ssrf.BlockedAddress("адреса недоступна з інтернету")


class Writer:
    def close(self):
        pass


async def test_tcp_check_open_and_closed_port():
    async def opened(ip, port):
        assert (ip, port) == ("93.184.216.34", 5432)
        return None, Writer()

    async def refused(ip, port):
        raise ConnectionRefusedError

    ok = await net.check_tcp("db.example.com:5432", resolver=public, opener=opened)
    assert ok.available == 1 and ok.response_ms is not None
    assert (await net.check_tcp("db.example.com:5432", resolver=public, opener=refused)).available == 0


async def test_checks_refuse_private_addresses():
    assert (await net.check_tcp("10.0.0.5:22", resolver=blocked)).available == 0
    assert (await net.check_ping("10.0.0.5", resolver=blocked)).available == 0


async def test_ping_check_results():
    async def partial(ip):
        return LINUX

    async def dead(ip):
        return "3 packets transmitted, 0 received, 100% packet loss, time 2051ms"

    r = await net.check_ping("example.com", resolver=public, runner=partial)
    assert (r.available, r.response_ms, round(r.packet_loss)) == (1, 12.5, 33)
    assert (await net.check_ping("example.com", resolver=public, runner=dead)).available == 0


async def test_ping_and_tcp_service_creation(client, user_factory):
    h = await user_factory()
    ok = await client.post("/api/targets", json={"name": "db", "type": "service", "check_type": "tcp",
                                                 "address": "db.example.com:5432"}, headers=h)
    assert ok.status_code == 201 and ok.json()["check_type"] == "tcp"
    ping = await client.post("/api/targets", json={"name": "gw", "type": "service", "check_type": "ping",
                                                   "address": "gw.example.com"}, headers=h)
    assert ping.status_code == 201
    for body in ({"check_type": "tcp", "address": "db.example.com"},
                 {"check_type": "ping", "address": "http://gw.example.com"},
                 {"check_type": "ping", "address": "gw.example.com:80"}):
        r = await client.post("/api/targets", json={"name": "x", "type": "service", **body}, headers=h)
        assert r.status_code == 422, body


async def test_server_ping_needs_address_and_public_ip(client, user_factory, monkeypatch):
    h = await user_factory()
    no_addr = await client.post("/api/targets", json={"name": "web-01", "type": "server", "ping_enabled": True}, headers=h)
    assert no_addr.status_code == 422
    ok = await client.post("/api/targets", json={"name": "web-01", "type": "server", "ping_enabled": True,
                                                 "address": "web-01.example.com"}, headers=h)
    assert ok.status_code == 201 and ok.json()["ping_enabled"] is True
    monkeypatch.setattr("app.services.targets.address_resolver", blocked)
    private = await client.post("/api/targets", json={"name": "web-02", "type": "server", "ping_enabled": True,
                                                      "address": "10.0.0.5"}, headers=h)
    assert private.status_code == 422


async def make_pinged_server(client, h):
    r = await client.post("/api/targets", json={"name": "web-01", "type": "server", "ping_enabled": True,
                                                "address": "web-01.example.com"}, headers=h)
    assert r.status_code == 201
    return r.json()


async def run_ping(target_id, result):
    async def fake(address):
        return result

    async with SessionLocal() as db:
        await checks.run_check(db, await db.get(Target, target_id), fake)
        await db.commit()


async def test_server_ping_stores_ping_metrics_and_keeps_last_seen(client, user_factory):
    h = await user_factory()
    srv = await make_pinged_server(client, h)
    await run_ping(srv["id"], CheckResult(1, 12.5, packet_loss=0.0))
    got = (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()
    assert got["latest"]["ping_available"] == 1 and got["latest"]["ping_ms"] == 12.5 and got["latest"]["packet_loss"] == 0
    assert got["last_seen"] is None  # last_seen веде лише агент


async def test_two_failed_pings_open_unavailable_incident(client, user_factory):
    h = await user_factory()
    srv = await make_pinged_server(client, h)
    down = CheckResult(0, None, packet_loss=100.0)
    await run_ping(srv["id"], down)
    key = (srv["id"], "ping_available", "")
    st = pipeline._states[key]
    pipeline._states[key] = type(st)(breach_since=st.breach_since - __import__("datetime").timedelta(seconds=31))
    await run_ping(srv["id"], down)
    [inc] = await incidents(client, h)
    assert inc["metric"] == "ping_available" and inc["severity"] == "critical"
    assert (await client.get(f"/api/targets/{srv['id']}", headers=h)).json()["status"] == "unavailable"


async def test_scheduler_picks_up_ping_servers_and_tcp_services(client, user_factory):
    h = await user_factory()
    await make_pinged_server(client, h)
    await server(client, h, "plain")  # сервер без ping – планувальник його не чіпає
    await client.post("/api/targets", json={"name": "db", "type": "service", "check_type": "tcp",
                                            "address": "db.example.com:5432"}, headers=h)
    seen = []

    async def fake(*args):
        seen.append(args)
        return CheckResult(1, 5.0)

    background._next_run.clear()
    background._running.clear()
    assert await background.schedule_due(fake) == 2
    await asyncio.sleep(0.3)
    assert len(seen) == 2
