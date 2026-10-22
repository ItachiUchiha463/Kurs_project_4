import httpx
import pytest

from app.checks import ssrf
from app.checks.http import check_http, status_ok

BLOCKED = ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1",
           "fd00::1", "224.0.0.1", "ff02::1", "100.64.0.1", "[::1]", "::ffff:127.0.0.1", "::ffff:10.0.0.5", "192.0.2.1"]


@pytest.mark.parametrize("host", BLOCKED)
async def test_non_global_ip_literals_are_blocked(host):
    with pytest.raises(ssrf.BlockedAddress):
        await ssrf.resolve_public(host)


async def test_public_ip_is_allowed():
    assert await ssrf.resolve_public("93.184.216.34") == "93.184.216.34"
    assert await ssrf.resolve_public("2606:2800:220:1:248:1893:25c8:1946")


def _fake_dns(monkeypatch, ips):
    async def getaddrinfo(self, host, port, **kw):
        return [(0, 0, 0, "", (ip, port)) for ip in ips]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", getaddrinfo)


async def test_domain_resolving_to_private_ip_is_blocked(monkeypatch):
    _fake_dns(monkeypatch, ["10.1.2.3"])
    with pytest.raises(ssrf.BlockedAddress):
        await ssrf.resolve_public("evil.example.com")


async def test_domain_with_one_private_answer_is_blocked(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34", "127.0.0.1"])  # змішана відповідь – типова атака
    with pytest.raises(ssrf.BlockedAddress):
        await ssrf.resolve_public("mixed.example.com")


async def test_localhost_name_is_blocked():
    with pytest.raises(ssrf.BlockedAddress):
        await ssrf.resolve_public("localhost")


async def test_check_blocks_private_target_without_connecting():
    def boom(request):
        raise AssertionError("з'єднання не мало відкриватись")
    r = await check_http("http://169.254.169.254/latest/meta-data", transport=httpx.MockTransport(boom))
    assert r.available == 0 and "інтернету" in r.error


async def _public(host, port):
    return "93.184.216.34"


async def test_check_connects_to_verified_ip_with_host_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["ip"], seen["host"] = request.url.host, request.headers["host"]
        return httpx.Response(200)

    r = await check_http("https://shop.example.ua/health", resolver=_public, transport=httpx.MockTransport(handler))
    assert r.available == 1 and r.status_code == 200 and r.response_ms is not None
    assert seen == {"ip": "93.184.216.34", "host": "shop.example.ua"}


async def test_redirect_to_private_address_is_blocked():
    async def resolver(host, port):
        return await ssrf.resolve_public(host, port) if host != "shop.example.ua" else "93.184.216.34"

    def handler(request):
        return httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})

    r = await check_http("http://shop.example.ua", resolver=resolver, transport=httpx.MockTransport(handler))
    assert r.available == 0 and "інтернету" in r.error


async def test_redirects_are_followed_up_to_three():
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        return httpx.Response(302, headers={"location": "/next"})

    r = await check_http("http://shop.example.ua", resolver=_public, transport=httpx.MockTransport(handler))
    assert r.available == 0 and r.error == "забагато перенаправлень" and n["i"] == 4


async def test_server_errors_are_unavailable_with_status_code():
    r = await check_http("http://shop.example.ua", resolver=_public,
                         transport=httpx.MockTransport(lambda req: httpx.Response(502)))
    assert r.available == 0 and r.status_code == 502


async def test_network_error_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")
    r = await check_http("http://shop.example.ua", resolver=_public, transport=httpx.MockTransport(handler))
    assert r.available == 0 and r.status_code == 0 and r.error == "ConnectError"


def test_expected_status_parsing():
    assert status_ok(200, "200-399") and status_ok(399, "200-399") and not status_ok(400, "200-399")
    assert status_ok(204, "200,204") and not status_ok(201, "200,204")
