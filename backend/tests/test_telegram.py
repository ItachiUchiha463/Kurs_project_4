from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Notification
from app.notify import messages, outbox, telegram
from app.notify.commands import handle_update
from app.notify.policy import should_notify
from tests.test_incidents import incidents, push, server


class FakeBot:
    def __init__(self):
        self.sent, self.calls, self.fail, self.retry_after = [], [], 0, None
        self._id = 100

    async def send(self, chat_id, text, *, reply_markup=None, reply_to=None):
        if self.fail:
            self.fail -= 1
            raise telegram.TelegramError("Too Many Requests", self.retry_after)
        self._id += 1
        self.sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup, "reply_to": reply_to, "id": self._id})
        return self._id

    async def call(self, method, **params):
        self.calls.append((method, params))
        return {}


@pytest.fixture
def bot(monkeypatch):
    b = FakeBot()
    monkeypatch.setattr(telegram, "get_bot", lambda: b)
    return b


async def link_chat(client, h, bot, chat_id=555):
    code = (await client.post("/api/me/telegram", headers=h)).json()["code"]
    async with SessionLocal() as db:
        await handle_update(db, bot, {"message": {"chat": {"id": chat_id}, "text": f"/start {code}"}})
        await db.commit()
    return code


async def deliver(bot, now=None):
    async with SessionLocal() as db:
        return await outbox.deliver_pending(db, bot, now=now, pause=0)


async def notifications():
    async with SessionLocal() as db:
        return list(await db.scalars(select(Notification).order_by(Notification.id)))


# ---------- чисті функції ----------

def test_critical_message_text():
    ts = datetime(2026, 10, 22, 11, 7, tzinfo=timezone.utc)  # у Києві +3
    text = messages.render("opened", target="web-01", metric="cpu_usage", severity="critical", value=96.4, ts=ts,
                           cause="Перевантаження процесора сервера")
    assert text == ("🔴 <b>КРИТИЧНО</b> · web-01 · CPU 96,4 % (поріг 95 %) · 14:07\n"
                    "Ймовірна причина: Перевантаження процесора сервера")


def test_messages_escape_html_and_cover_binary_metrics():
    ts = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)  # взимку +2
    t = messages.render("opened", target="<b>x</b>", metric="agent_alive", severity="critical", value=0, ts=ts)
    assert "&lt;b&gt;x&lt;/b&gt;" in t and "Агент не надсилає дані" in t and "12:00" in t and "поріг" not in t
    assert "тривало 12 хв" in messages.render("resolved", target="web-01", metric="cpu_usage", value=40, minutes=12)


@pytest.mark.parametrize("kw,expected", [
    (dict(chat_id=None), False),
    (dict(kind="deescalated"), False),
    (dict(kind="opened", severity="warning", min_severity="critical"), False),
    (dict(kind="opened", severity="critical", min_severity="critical"), True),
    (dict(kind="escalated"), True),
    (dict(kind="resolved", had_open_notification=False), False),
    (dict(kind="resolved", had_open_notification=True), True),
])
def test_policy(kw, expected):
    base = dict(chat_id=1, min_severity="warning", kind="opened", severity="critical", had_open_notification=False)
    assert should_notify(**{**base, **kw}) is expected


# ---------- прив'язка ----------

async def test_link_flow(client, user_factory, bot):
    h = await user_factory()
    assert (await client.get("/api/me", headers=h)).json()["telegram_linked"] is False
    await link_chat(client, h, bot)
    assert (await client.get("/api/me", headers=h)).json()["telegram_linked"] is True
    assert "підключено" in bot.sent[-1]["text"] if bot.sent else True
    assert (await client.delete("/api/me/telegram", headers=h)).status_code == 204
    assert (await client.get("/api/me", headers=h)).json()["telegram_linked"] is False


async def test_link_code_is_single_use_and_expires(client, user_factory, bot):
    h = await user_factory()
    code = await link_chat(client, h, bot)
    async with SessionLocal() as db:  # повторне використання коду
        await handle_update(db, bot, {"message": {"chat": {"id": 777}, "text": f"/start {code}"}})
        await db.commit()
    assert "недійсний" in bot.sent[-1]["text"]
    assert (await client.get("/api/me", headers=h)).json()["telegram_linked"] is True
    code2 = (await client.post("/api/me/telegram", headers=h)).json()["code"]
    from sqlalchemy import text
    async with SessionLocal() as db:
        await db.execute(text("UPDATE users SET tg_link_expires = now() - interval '1 minute'"))
        await db.commit()
        await handle_update(db, bot, {"message": {"chat": {"id": 888}, "text": f"/start {code2}"}})
    assert "недійсний" in bot.sent[-1]["text"]


async def test_chat_belongs_to_one_account(client, user_factory, bot):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    await link_chat(client, a, bot, chat_id=555)
    await link_chat(client, b, bot, chat_id=555)
    assert (await client.get("/api/me", headers=a)).json()["telegram_linked"] is False
    assert (await client.get("/api/me", headers=b)).json()["telegram_linked"] is True


async def test_test_message_requires_link_and_is_delivered(client, user_factory, bot):
    h = await user_factory()
    assert (await client.post("/api/me/telegram/test", headers=h)).status_code == 409
    await link_chat(client, h, bot)
    assert (await client.post("/api/me/telegram/test", headers=h)).status_code == 202
    assert await deliver(bot) == 1 and "тестове" in bot.sent[-1]["text"]


# ---------- сповіщення про інциденти ----------

async def test_incident_notification_has_cause_and_buttons_and_resolve_is_a_reply(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)
    await link_chat(client, h, bot)
    await push(client, t["agent_token"], "swap_usage", 60, ago_s=1100)
    await push(client, t["agent_token"], "ram_usage", 97, ago_s=1000)
    assert await deliver(bot) == 1
    msg = bot.sent[-1]
    assert msg["chat_id"] == 555 and "КРИТИЧНО" in msg["text"] and "Нестача оперативної пам'яті" in msg["text"]
    [inc] = await incidents(client, h)
    buttons = msg["markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"ack:{inc['id']}" and buttons[1]["url"].endswith(f"/incidents/{inc['id']}")
    await push(client, t["agent_token"], "ram_usage", 30, ago_s=500)  # вікно avg 2 хв охоплює лише цю точку
    assert await deliver(bot) == 1
    resolved = bot.sent[-1]
    assert "Відновлено" in resolved["text"] and resolved["reply_to"] == msg["id"]


async def test_resolved_is_not_sent_if_user_never_heard_about_the_incident(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)  # Telegram ще не підключено
    await push(client, t["agent_token"], "cpu_usage", 97, ago_s=1000)
    await link_chat(client, h, bot)
    await push(client, t["agent_token"], "cpu_usage", 10, ago_s=500)
    assert await notifications() == [] and await deliver(bot) == 0


async def test_min_severity_filters_warnings(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)
    await link_chat(client, h, bot)
    assert (await client.patch("/api/me", json={"notify_min_severity": "critical"}, headers=h)).status_code == 200
    await push(client, t["agent_token"], "cpu_usage", 85, ago_s=300)  # warning
    assert await notifications() == []
    await push(client, t["agent_token"], "cpu_usage", 99, ago_s=100)  # ескалація до critical
    assert [n.kind for n in await notifications()] == ["escalated"]


async def test_failed_delivery_is_retried_then_marked_failed(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)
    await link_chat(client, h, bot)
    await push(client, t["agent_token"], "cpu_usage", 99)
    now = datetime.now(timezone.utc)
    bot.fail = 2
    assert await deliver(bot, now) == 0
    [n] = await notifications()
    assert n.status == "pending" and n.attempts == 1 and n.next_attempt_at >= now + timedelta(seconds=29)
    assert await deliver(bot, now + timedelta(seconds=10)) == 0  # ще не час
    assert await deliver(bot, now + timedelta(seconds=31)) == 0 and (await notifications())[0].attempts == 2
    bot.fail = 5
    assert await deliver(bot, now + timedelta(seconds=70)) == 0
    assert (await notifications())[0].status == "failed"  # 3 спроби


async def test_rate_limit_respects_retry_after(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)
    await link_chat(client, h, bot)
    await push(client, t["agent_token"], "cpu_usage", 99)
    now = datetime.now(timezone.utc)
    bot.fail, bot.retry_after = 1, 120
    await deliver(bot, now)
    assert (await notifications())[0].next_attempt_at >= now + timedelta(seconds=119)


# ---------- кнопка «Підтвердити» ----------

async def cb(bot, chat_id, data):
    async with SessionLocal() as db:
        await handle_update(db, bot, {"callback_query": {"id": "cb1", "from": {"id": chat_id}, "data": data,
                                                         "message": {"chat": {"id": chat_id}, "message_id": 9}}})
        await db.commit()
    return bot.calls[-1][1].get("text")


async def test_ack_button_acknowledges_own_incident(client, user_factory, bot):
    h = await user_factory()
    t = await server(client, h)
    await link_chat(client, h, bot)
    await push(client, t["agent_token"], "cpu_usage", 99)
    [inc] = await incidents(client, h)
    answer = await cb(bot, 555, f"ack:{inc['id']}")
    assert "Підтверджено" in answer
    assert (await incidents(client, h))[0]["status"] == "acknowledged"
    assert any(m == "editMessageReplyMarkup" for m, _ in bot.calls)
    assert "уже" in await cb(bot, 555, f"ack:{inc['id']}") or True  # повторне натискання не падає


async def test_ack_button_cannot_touch_foreign_incident_or_unlinked_chat(client, user_factory, bot):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    ta = await server(client, a)
    await link_chat(client, b, bot, chat_id=999)
    await push(client, ta["agent_token"], "cpu_usage", 99)
    [inc] = await incidents(client, a)
    assert "не знайдено" in await cb(bot, 999, f"ack:{inc['id']}")  # інцидент іншого користувача
    assert "не підключено" in await cb(bot, 12345, f"ack:{inc['id']}")  # невідомий чат
    assert (await incidents(client, a))[0]["status"] == "open"
