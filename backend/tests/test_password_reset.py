import re

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.notify import telegram

EMAIL = "ada@example.com"
OLD, NEW = "Passw0rd1", "N3wPassword"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, body, **kw):
        self.sent.append((chat_id, body))
        return 1


@pytest.fixture
def bot(monkeypatch):
    b = FakeBot()
    monkeypatch.setattr(telegram, "get_bot", lambda: b)
    return b


async def register(client, link_telegram=True):
    r = await client.post("/api/auth/register", json={"email": EMAIL, "password": OLD, "full_name": "Ада"})
    assert r.status_code == 201
    if link_telegram:
        async with SessionLocal() as db:
            await db.execute(text("UPDATE users SET telegram_chat_id = 777"))
            await db.commit()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def token_from(bot):
    return re.search(r"token=([\w-]+)", bot.sent[-1][1]).group(1)


async def login(client, password):
    return await client.post("/api/auth/login", json={"email": EMAIL, "password": password})


async def test_unknown_email_and_unlinked_user_get_the_same_answer_and_nothing_is_sent(client, bot):
    await register(client, link_telegram=False)
    answers = [await client.post("/api/auth/forgot", json={"email": e}) for e in ("nobody@example.com", EMAIL)]
    assert [a.status_code for a in answers] == [202, 202] and answers[0].json() == answers[1].json()
    assert bot.sent == []


async def test_reset_flow_changes_password_and_ends_old_sessions(client, bot):
    old_headers = await register(client)
    assert (await client.post("/api/auth/forgot", json={"email": EMAIL})).status_code == 202
    assert bot.sent[0][0] == 777 and "/reset?token=" in bot.sent[0][1]
    token = token_from(bot)
    assert (await client.post("/api/auth/reset", json={"token": token, "password": NEW})).status_code == 204
    assert (await login(client, OLD)).status_code == 401
    assert (await login(client, NEW)).status_code == 200
    assert (await client.get("/api/me", headers=old_headers)).status_code == 401  # старий JWT після скидання не діє


async def test_reset_token_is_single_use(client, bot):
    await register(client)
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    token = token_from(bot)
    assert (await client.post("/api/auth/reset", json={"token": token, "password": NEW})).status_code == 204
    again = await client.post("/api/auth/reset", json={"token": token, "password": "An0therPass"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_reset_token"
    assert (await login(client, NEW)).status_code == 200


async def test_expired_and_garbage_tokens_are_refused(client, bot):
    await register(client)
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    token = token_from(bot)
    async with SessionLocal() as db:
        await db.execute(text("UPDATE users SET pwd_reset_expires = now() - interval '1 minute'"))
        await db.commit()
    for t in (token, "garbage"):
        r = await client.post("/api/auth/reset", json={"token": t, "password": NEW})
        assert r.status_code == 400
    assert (await login(client, OLD)).status_code == 200  # пароль не змінився


async def test_new_password_must_follow_the_same_rules(client, bot):
    await register(client)
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    r = await client.post("/api/auth/reset", json={"token": token_from(bot), "password": "short"})
    assert r.status_code == 422


async def test_forgot_is_rate_limited(client, bot):
    codes = [(await client.post("/api/auth/forgot", json={"email": EMAIL})).status_code for _ in range(7)]
    assert codes == [202] * 5 + [429] * 2


async def test_logout_all_invalidates_every_token(client):
    h1 = await register(client, link_telegram=False)
    h2 = {"Authorization": "Bearer " + (await login(client, OLD)).json()["access_token"]}
    assert (await client.get("/api/me", headers=h2)).status_code == 200
    assert (await client.post("/api/auth/logout-all", headers=h1)).status_code == 204
    assert (await client.get("/api/me", headers=h1)).status_code == 401
    assert (await client.get("/api/me", headers=h2)).status_code == 401
    assert (await login(client, OLD)).status_code == 200  # увійти знову можна


async def test_password_reset_does_not_clear_other_users_login_lock(client, bot):
    from app.services import auth as auth_service
    await register(client)
    auth_service.login_failures.fail("victim@example.com|1.2.3.4")
    for _ in range(9):
        auth_service.login_failures.fail("victim@example.com|1.2.3.4")
    assert auth_service.login_failures.locked("victim@example.com|1.2.3.4")
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    assert (await client.post("/api/auth/reset", json={"token": token_from(bot), "password": NEW})).status_code == 204
    assert auth_service.login_failures.locked("victim@example.com|1.2.3.4")  # чуже блокування лишилось


async def test_reset_messages_per_email_are_limited_but_answer_is_the_same(client, bot, monkeypatch):
    from app.api import auth as auth_api
    await register(client)
    monkeypatch.setattr(auth_api.reset_limiter, "limit", 1000)  # перевіряємо ліміт за email, а не за IP
    answers = [await client.post("/api/auth/forgot", json={"email": EMAIL}) for _ in range(5)]
    assert {a.status_code for a in answers} == {202}
    assert len(bot.sent) == 3  # 4-й і 5-й запити мовчки проігноровано
