"""Команди й кнопки бота (ТЗ 9.1): /start <код> прив'язує чат, «Підтвердити» підтверджує інцидент.

Сюди потрапляє кожне оновлення від Telegram (цикл _bot_loop у background.py). Бот розуміє лише дві речі:
  1. Команду «/start <код>»: код користувач бере в «Профілі». Якщо код дійсний, чат Telegram прив'язується
     до його облікового запису й далі сповіщення йдуть туди.
  2. Натискання кнопки «Підтвердити» під сповіщенням про інцидент (callback_query з даними «ack:<id інциденту>»).
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models import User
from app.services import incidents, telegram_link

log = logging.getLogger("vigil.telegram")
HELP = "Щоб підключити сповіщення, відкрийте Vigil → Профіль → «Підключити Telegram» і перейдіть за посиланням."


async def handle_update(db: AsyncSession, bot, update: dict) -> None:
    """Обробляє одне оновлення від Telegram: або натискання кнопки, або текстове повідомлення /start."""
    if "callback_query" in update:
        await _callback(db, bot, update["callback_query"])
    elif "message" in update and (text := (update["message"].get("text") or "")).startswith("/start"):
        chat_id = update["message"]["chat"]["id"]
        code = text.partition(" ")[2].strip()  # усе після «/start » – це код прив'язки
        user = await telegram_link.link_by_code(db, code, chat_id) if code else None
        reply = f"✅ Telegram підключено до облікового запису {user.full_name}." if user else \
            ("Код недійсний або прострочений. Створіть нове посилання у Vigil." if code else HELP)
        await bot.send(chat_id, reply)


async def _callback(db: AsyncSession, bot, cb: dict) -> None:
    """Натискання кнопки під повідомленням. Дані кнопки мають вигляд «ack:42» (підтвердити інцидент №42)."""
    kind, _, raw_id = (cb.get("data") or "").partition(":")
    if kind != "ack" or not raw_id.isdigit():
        return
    # Користувача визначаємо за чатом, з якого натиснули: підтвердити може лише власник прив'язаного чату.
    user = await db.scalar(select(User).where(User.telegram_chat_id == cb["from"]["id"]))
    try:
        if not user:
            raise AppError("Чат не підключено до облікового запису")
        await incidents.acknowledge(db, user, int(raw_id))
        answer = "Підтверджено: ви займаєтесь цим інцидентом"
        if msg := cb.get("message"):  # прибираємо кнопку, щоб не натискали вдруге
            await bot.call("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                           reply_markup={"inline_keyboard": [[]]})
    except AppError as e:
        answer = e.message or "Не вдалося"
    await bot.call("answerCallbackQuery", callback_query_id=cb["id"], text=answer)
