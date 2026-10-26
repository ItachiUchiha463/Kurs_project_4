"""Розбір адрес об'єктів: спільний для схем, перевірок і сервісів."""


def split_host_port(address: str) -> tuple[str, int]:
    """«host:port» або «[ipv6]:port»; ValueError, якщо порт не вказано чи він поза 1..65535."""
    host, sep, port = address.strip().rpartition(":")
    if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Адреса має вигляд хост:порт, порт – від 1 до 65535")
    return host.strip("[]"), int(port)
