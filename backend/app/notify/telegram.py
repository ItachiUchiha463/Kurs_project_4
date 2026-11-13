"""Клієнт Telegram Bot API (ТЗ 9.1): запити через httpx, отримання команд long polling-ом.

Telegram Bot API – це звичайні HTTPS-запити на адресу https://api.telegram.org/bot<токен>/<метод>.
Тут лише тонка обгортка: надіслати повідомлення, отримати нові повідомлення/натискання кнопок.
Бізнес-логіка бота (що робити з /start чи кнопкою) – у notify/commands.py.
"""
import logging

import httpx

from app.config import settings

log = logging.getLogger("vigil.telegram")


class TelegramError(Exception):
    """Помилка Telegram (мережа або відмова API). retry_after – скільки секунд Telegram просить зачекати (при ліміті)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class Bot:
    """Один бот. Токен входить в адресу запитів, тому в повідомленнях про помилки його не показуємо."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self._url = f"https://api.telegram.org/bot{token}/"
        self._client = client or httpx.AsyncClient(timeout=35)  # довший за long polling (25 с)

    async def call(self, method: str, **params) -> dict | list:
        """Виклик довільного методу Bot API; повертає поле result або кидає TelegramError."""
        try:
            r = await self._client.post(self._url + method, json=params)
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(type(e).__name__) from None  # у повідомленні не лишаємо URL з токеном
        if not body.get("ok"):
            retry = (body.get("parameters") or {}).get("retry_after")
            raise TelegramError(str(body.get("description", "помилка Telegram")), retry)
        return body["result"]

    async def send(self, chat_id: int, text: str, *, reply_markup: dict | None = None, reply_to: int | None = None) -> int:
        """Надсилає повідомлення; повертає його id (потрібен, щоб потім відповісти на нього «відновлено»)."""
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup  # кнопки під повідомленням
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return (await self.call("sendMessage", **params))["message_id"]

    async def updates(self, offset: int, timeout: int = 25) -> list[dict]:
        """Long polling: запит «висить» до 25 с і повертається, щойно з'являються нові повідомлення чи натискання кнопок."""
        return await self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"])


_bot: Bot | None = None  # єдиний екземпляр бота на процес


def get_bot() -> Bot | None:
    """None, якщо TELEGRAM_BOT_TOKEN не задано: тоді сповіщення просто не надсилаються."""
    global _bot
    if _bot is None and settings.telegram_bot_token:
        _bot = Bot(settings.telegram_bot_token)
    return _bot


def incident_keyboard(incident_id: int) -> dict:
    """Кнопки під сповіщенням: «Підтвердити» (callback ack:<id>, його розбирає notify/commands.py) і «Відкрити» (посилання на картку)."""
    return {"inline_keyboard": [[
        {"text": "✅ Підтвердити", "callback_data": f"ack:{incident_id}"},
        {"text": "🔗 Відкрити", "url": f"{settings.public_url.rstrip('/')}/incidents/{incident_id}"},
    ]]}
