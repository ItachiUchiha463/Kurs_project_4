"""HTTP-перевірка (ТЗ 5.2): GET на перевірений IP, без автоматичних редиректів, тіло відповіді не читається."""
import asyncio
import time
from dataclasses import dataclass

import httpx

from app.checks import ssrf

TIMEOUT_S = 10
TOTAL_TIMEOUT_S = 30  # timeout httpx діє на кожен крок окремо: повільний «крапельний» сервер інакше тримав би перевірку вічно
MAX_REDIRECTS = 3
REDIRECTS = {301, 302, 303, 307, 308}


@dataclass
class CheckResult:
    available: int
    response_ms: float | None = None
    status_code: int = 0
    error: str | None = None


def status_ok(code: int, expected: str) -> bool:
    """expected: «200-399» або «200,204»."""
    for part in expected.split(","):
        lo, _, hi = part.strip().partition("-")
        if lo.isdigit() and int(lo) <= code <= int(hi or lo):
            return True
    return False


async def check_http(url: str, expected: str = "200-399", *, resolver=None, transport=None) -> CheckResult:
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_S):
            return await _check(url, expected, resolver or ssrf.resolve_public, transport)
    except TimeoutError:
        return CheckResult(0, error="timeout")


async def _check(url: str, expected: str, resolver, transport) -> CheckResult:
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                u = httpx.URL(url)
                ip = await resolver(u.host, u.port or (443 if u.scheme == "https" else 80))  # IP перевіряється на кожному кроці
                async with client.stream("GET", u.copy_with(host=ip), headers={"Host": u.netloc.decode()},
                                         extensions={"sni_hostname": u.host}) as r:
                    code, location = r.status_code, r.headers.get("location")
                if code in REDIRECTS and location:
                    url = str(u.join(location))
                    continue
                ms = (time.perf_counter() - t0) * 1000
                return CheckResult(int(status_ok(code, expected)), ms, code)
            return CheckResult(0, error="забагато перенаправлень")
    except ssrf.BlockedAddress as e:
        return CheckResult(0, error=str(e))
    except httpx.HTTPError as e:
        return CheckResult(0, error=type(e).__name__)
