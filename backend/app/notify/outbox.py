"""Черга сповіщень (outbox): записи створюються в тій самій транзакції, що й інцидент, а відправляє фонова задача.

Так сповіщення не губляться при перезапуску й не блокують прийом метрик; невдалі повторюються до 3 разів (ТЗ 9.1).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Diagnosis, Incident, Notification, Rule, Target, User
from app.notify import messages, telegram
from app.notify.policy import should_notify
from app.repositories import incidents as incidents_repo

if TYPE_CHECKING:  # pipeline сам викликає enqueue, тому тут лише для типів
    from app.services.pipeline import Change

log = logging.getLogger("vigil.notify")
MAX_ATTEMPTS = 3
RETRY_S = 30
SENT_KINDS = ("opened", "escalated")


async def _had_open_notification(db: AsyncSession, incident_id: int) -> bool:
    return await db.scalar(select(Notification.id).where(
        Notification.incident_id == incident_id, Notification.kind.in_(SENT_KINDS),
        Notification.status.in_(("pending", "sent"))).limit(1)) is not None


async def enqueue(db: AsyncSession, changes: "list[Change]") -> int:
    if telegram.get_bot() is None or not changes:
        return 0
    n = 0
    for c in changes:
        user = await db.get(User, c.target.owner_id)
        if not should_notify(chat_id=user.telegram_chat_id, min_severity=user.notify_min_severity, kind=c.kind,
                             severity=c.incident.severity,
                             had_open_notification=c.kind == "resolved" and await _had_open_notification(db, c.incident.id)):
            continue
        db.add(Notification(incident_id=c.incident.id, chat_id=user.telegram_chat_id, kind=c.kind, status="pending"))
        n += 1
    return n


def enqueue_test(db: AsyncSession, chat_id: int) -> None:
    db.add(Notification(incident_id=None, chat_id=chat_id, kind="test", status="pending"))


async def _render(db: AsyncSession, n: Notification) -> tuple[str, dict | None, int | None]:
    if n.kind == "test":
        return messages.render("test"), None, None
    inc = await db.get(Incident, n.incident_id)
    target = await db.get(Target, inc.target_id)
    events = await incidents_repo.events(db, inc.id)
    last = next((e for e in reversed(events) if e.type == n.kind), None)
    value = last.value if last and last.value is not None else (inc.value_at_open or 0.0)
    if n.kind == "resolved":
        minutes = int(((inc.resolved_at or datetime.now(timezone.utc)) - inc.started_at).total_seconds() // 60)
        reply_to = await db.scalar(select(Notification.message_id).where(
            Notification.incident_id == inc.id, Notification.chat_id == n.chat_id, Notification.status == "sent",
            Notification.kind.in_(SENT_KINDS)).order_by(Notification.id.desc()).limit(1))
        text = messages.render("resolved", target=target.name, metric=inc.metric, instance=inc.instance, value=value, minutes=minutes)
        return text, None, reply_to
    row = (await db.execute(select(Rule.cause).join(Diagnosis, Diagnosis.rule_id == Rule.id)
                            .where(Diagnosis.incident_id == inc.id))).first()
    text = messages.render(n.kind, target=target.name, metric=inc.metric, instance=inc.instance, severity=inc.severity,
                           value=value, ts=last.ts if last else inc.started_at, cause=row[0] if row else None)
    return text, telegram.incident_keyboard(inc.id), None


async def deliver_pending(db: AsyncSession, bot, now: datetime | None = None, pause: float = 1.0) -> int:
    """Надсилає сповіщення, час яких настав; пауза між повідомленнями – ліміт Telegram 1 повідомлення/с на чат."""
    now = now or datetime.now(timezone.utc)
    rows = list(await db.scalars(select(Notification).where(
        Notification.status == "pending", Notification.next_attempt_at <= now).order_by(Notification.id).limit(20)))
    sent = 0
    for n in rows:
        try:
            text, markup, reply_to = await _render(db, n)
            n.message_id = await bot.send(n.chat_id, text, reply_markup=markup, reply_to=reply_to)
            n.status, n.sent_at, sent = "sent", now, sent + 1
        except telegram.TelegramError as e:
            n.attempts += 1
            n.error = str(e)[:200]
            if n.attempts >= MAX_ATTEMPTS:
                n.status = "failed"
                log.error("сповіщення не доставлено", extra={"notification_id": n.id, "error": n.error})
            else:
                n.next_attempt_at = now + timedelta(seconds=e.retry_after or RETRY_S)
        except Exception as e:  # помилка в нашому коді: без цього одне «погане» сповіщення блокувало б усю чергу
            n.status, n.error = "failed", repr(e)[:200]
            log.exception("збій підготовки сповіщення", extra={"notification_id": n.id})
        await db.commit()  # по одному, щоб збій посеред пакета не призвів до повторної відправки вже надісланих
        if pause:
            await asyncio.sleep(pause)
    return sent
