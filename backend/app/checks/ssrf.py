"""Захист від SSRF (ТЗ розд. 3): запити з сервера йдуть лише на глобальні IP, перевірені під час кожного запиту."""
import asyncio
import ipaddress
import socket


class BlockedAddress(Exception):
    """Адреса приватна, loopback, link-local, зарезервована або не визначається."""


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    ip = ipaddress.ip_address(text.split("%", 1)[0])  # fe80::1%eth0 → fe80::1
    return ip.ipv4_mapped or ip if ip.version == 6 else ip  # ::ffff:127.0.0.1 перевіряємо як 127.0.0.1


def _allowed(ip) -> bool:
    # is_global сам по собі пропускає multicast (224.0.0.0/4), а ТЗ вимагає його блокувати
    return ip.is_global and not ip.is_multicast


async def resolve_public(host: str, port: int = 443) -> str:
    """Повертає перевірений IP. Якщо хоч одна з адрес домену не глобальна – відмова (проти DNS rebinding)."""
    try:
        ips = [_ip(host.strip("[]"))]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise BlockedAddress("адреса не визначається") from None
        ips = [_ip(info[4][0]) for info in infos]
    if not ips or not all(_allowed(ip) for ip in ips):
        raise BlockedAddress("адреса недоступна з інтернету")
    return str(ips[0])
