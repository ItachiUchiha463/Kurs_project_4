"""Захист від SSRF (ТЗ розд. 3): запити з сервера йдуть лише на глобальні IP, перевірені під час кожного запиту.

Що таке SSRF (Server-Side Request Forgery). Користувач вказує адресу сервісу, і САМ СЕРВЕР Vigil іде туди
з HTTP-перевіркою. Без захисту зловмисник міг би вказати «http://localhost:5432» або «http://10.0.0.5/admin» і змусити
сервер звертатися до внутрішньої мережі, звідки видно те, що ззовні недоступне.

Захист: перед кожною перевіркою адреса перетворюється на IP, і якщо він не «глобальний» (приватний, loopback,
link-local, multicast, зарезервований) – перевірка відхиляється. Саме перевірений IP використовується для з'єднання
(а не ім'я домену), щоб між перевіркою й запитом ім'я не встигло «переїхати» на внутрішню адресу (DNS rebinding).
"""
import asyncio
import ipaddress
import socket


class BlockedAddress(Exception):
    """Адреса приватна, loopback, link-local, зарезервована або не визначається."""


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Текст -> об'єкт IP. IPv4, загорнуту в IPv6, перевіряємо як IPv4, щоб її не можна було використати для обходу."""
    ip = ipaddress.ip_address(text.split("%", 1)[0])  # fe80::1%eth0 → fe80::1
    return ip.ipv4_mapped or ip if ip.version == 6 else ip  # ::ffff:127.0.0.1 перевіряємо як 127.0.0.1


def _allowed(ip) -> bool:
    """Дозволені лише публічні адреси інтернету."""
    # is_global сам по собі пропускає multicast (224.0.0.0/4), а ТЗ вимагає його блокувати
    return ip.is_global and not ip.is_multicast


async def resolve_public(host: str, port: int = 443) -> str:
    """Повертає перевірений IP. Якщо хоч одна з адрес домену не глобальна – відмова (проти DNS rebinding)."""
    try:
        ips = [_ip(host.strip("[]"))]  # host уже є IP-адресою
    except ValueError:
        # Це ім'я домену: запитуємо в DNS усі його адреси.
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise BlockedAddress("адреса не визначається") from None
        ips = [_ip(info[4][0]) for info in infos]
    # Достатньо однієї недозволеної адреси серед усіх, щоб відмовити: інакше домен із двома записами
    # (публічним і внутрішнім) міг би обійти перевірку.
    if not ips or not all(_allowed(ip) for ip in ips):
        raise BlockedAddress("адреса недоступна з інтернету")
    return str(ips[0])
