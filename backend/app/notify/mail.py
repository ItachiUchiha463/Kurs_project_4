"""Листи через SMTP (STARTTLS): підтвердження пошти й скидання пароля. Лише стандартна бібліотека, у потоці, щоб не зупиняти event loop."""
import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


class MailError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.smtp_host)


def _send(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from or settings.smtp_user, to, subject
    msg.set_content(body)
    try:
        await asyncio.to_thread(_send, msg)
    except (OSError, smtplib.SMTPException) as e:
        raise MailError(type(e).__name__) from None  # у повідомленні не лишаємо адресу сервера чи логін
