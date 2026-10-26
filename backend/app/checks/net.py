"""TCP- і ping-перевірки (ТЗ 5.2): як і HTTP, лише на перевірений публічний IP (захист від SSRF)."""
import asyncio
import platform
import re
import time

from app.addresses import split_host_port  # noqa: F401 – лишається доступним як net.split_host_port
from app.checks import ssrf
from app.checks.http import CheckResult

TCP_TIMEOUT_S = 10
PING_COUNT = 3
PING_TIMEOUT_S = 2


async def check_tcp(address: str, *, resolver=None, opener=None) -> CheckResult:
    resolver, opener = resolver or ssrf.resolve_public, opener or asyncio.open_connection
    try:
        host, port = split_host_port(address)
        ip = await resolver(host, port)
        t0 = time.perf_counter()
        _, writer = await asyncio.wait_for(opener(ip, port), TCP_TIMEOUT_S)
        ms = (time.perf_counter() - t0) * 1000
        writer.close()
        return CheckResult(1, ms)
    except ssrf.BlockedAddress as e:
        return CheckResult(0, error=str(e))
    except (OSError, asyncio.TimeoutError, ValueError) as e:
        return CheckResult(0, error=type(e).__name__)


def parse_ping(output: str) -> tuple[float, float | None]:
    """(частка втрачених пакетів у %, середній час у мс); працює з виводом iputils (Linux) і Windows."""
    loss = re.search(r"(\d+(?:\.\d+)?)%", output)
    avg = re.search(r"=\s*[\d.]+/([\d.]+)/[\d.]+", output) or re.search(r"=\s*(\d+)\D*$", output.strip())
    return (float(loss.group(1)) if loss else 100.0), (float(avg.group(1)) if avg else None)


async def _ping_binary(ip: str) -> str:
    win = platform.system() == "Windows"
    args = ["ping", "-n", str(PING_COUNT), "-w", str(PING_TIMEOUT_S * 1000), ip] if win else \
        ["ping", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT_S), ip]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), PING_COUNT * (PING_TIMEOUT_S + 1) + 5)
    return out.decode(errors="replace")


async def check_ping(address: str, *, resolver=None, runner=None) -> CheckResult:
    """available = 1, якщо дійшов хоча б один пакет; packet_loss у відсотках."""
    resolver, runner = resolver or ssrf.resolve_public, runner or _ping_binary
    try:
        ip = await resolver(address.strip(), 0)
        loss, avg = parse_ping(await runner(ip))
    except ssrf.BlockedAddress as e:
        return CheckResult(0, error=str(e))
    except (OSError, asyncio.TimeoutError) as e:  # немає бінарника ping або він завис
        return CheckResult(0, error=type(e).__name__)
    return CheckResult(int(loss < 100), avg, packet_loss=loss)
