import re
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.notify import mail
from tests.helpers import now

EMAIL, PASSWORD = "ada@example.com", "Passw0rd1"


@pytest.fixture
def outbox(monkeypatch):
    """Пошту ввімкнено, а листи збираються в список замість SMTP."""
    sent = []

    async def send(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(mail, "send", send)
    return sent


def token_in(letter) -> str:
    return re.search(r"token=([\w-]+)", letter[2]).group(1)


async def register(client):
    return await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "Ада"})


async def login(client, password=PASSWORD):
    return await client.post("/api/auth/login", json={"email": EMAIL, "password": password})


async def test_register_sends_letter_and_gives_no_token(client, outbox):
    r = await register(client)
    assert r.status_code == 201 and r.json()["access_token"] is None and r.json()["verify_email"] is True
    assert len(outbox) == 1 and outbox[0][0] == EMAIL and "/verify?token=" in outbox[0][2]


async def test_login_is_blocked_until_email_is_verified(client, outbox):
    await register(client)
    blocked = await login(client)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "email_not_verified"
    assert len(outbox) == 2  # вхід із правильним паролем надіслав новий лист
    assert (await client.post("/api/auth/verify", json={"token": token_in(outbox[1])})).status_code == 200
    assert (await login(client)).status_code == 200


async def test_verification_link_logs_in_and_works_once(client, outbox):
    await register(client)
    token = token_in(outbox[0])
    r = await client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert (await client.get("/api/me", headers={"Authorization": "Bearer " + r.json()["access_token"]})).status_code == 200
    assert (await client.post("/api/auth/verify", json={"token": token})).status_code == 400


async def test_expired_verification_link_is_rejected(client, outbox):
    await register(client)
    async with SessionLocal() as db:
        await db.execute(text("UPDATE users SET verify_expires = :t"), {"t": now() - timedelta(minutes=1)})
        await db.commit()
    assert (await client.post("/api/auth/verify", json={"token": token_in(outbox[0])})).status_code == 400


async def test_resend_on_login_is_limited_to_three_per_hour(client, outbox):
    await register(client)
    for _ in range(5):
        assert (await login(client)).status_code == 403
    assert len(outbox) == 1 + 3


async def test_reset_link_arrives_by_email_and_changes_password(client, outbox):
    await register(client)
    await client.post("/api/auth/verify", json={"token": token_in(outbox[0])})
    outbox.clear()
    assert (await client.post("/api/auth/forgot", json={"email": EMAIL})).status_code == 202
    assert len(outbox) == 1 and "/reset?token=" in outbox[0][2]
    r = await client.post("/api/auth/reset", json={"token": token_in(outbox[0]), "password": "N3wPassword"})
    assert r.status_code == 204
    assert (await login(client, "N3wPassword")).status_code == 200


async def test_reset_letter_is_not_sent_to_unverified_address(client, outbox):
    await register(client)
    outbox.clear()
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    assert outbox == []


async def test_without_smtp_register_still_gives_token(client):
    r = await register(client)
    assert r.json()["access_token"] and (await login(client)).status_code == 200
