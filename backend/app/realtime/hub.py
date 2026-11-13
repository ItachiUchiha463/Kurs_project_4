"""WebSocket-хаб (ТЗ 10.1): «кімнати» за user_id, тож подія одного користувача не потрапляє іншому.

Події публікуються лише після коміту транзакції, інакше клієнт міг би побачити інцидент, якого потім не існує.

Як це влаштовано:
  1. Браузер відкриває WebSocket (api/ws.py) і «заходить у кімнату» свого користувача (Hub.join).
  2. Код бізнес-логіки (pipeline, incidents) НЕ шле повідомлення одразу, а викликає publish_after_commit():
     подія кладеться в чергу всередині сесії БД.
  3. Слухачі подій SQLAlchemy (after_commit / after_rollback) переглядають чергу: після УСПІШНОГО коміту
     події відправляються клієнтам, а при відкаті транзакції – просто відкидаються.
Так браузер ніколи не побачить зміну, якої насправді не відбулося.
"""
import asyncio
import contextlib

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.tasks import spawn

SEND_TIMEOUT_S = 2  # скільки чекаємо, поки клієнт прийме повідомлення, перш ніж вважати його «завислим»


class Hub:
    """Реєстр відкритих WebSocket-з'єднань: для кожного користувача – множина його з'єднань (вкладок браузера)."""

    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = {}

    def join(self, user_id: int, ws: WebSocket) -> None:
        """Додає з'єднання до кімнати користувача."""
        self.rooms.setdefault(user_id, set()).add(ws)

    def leave(self, user_id: int, ws: WebSocket) -> None:
        """Прибирає з'єднання; порожню кімнату видаляє, щоб словник не ріс."""
        self.rooms.get(user_id, set()).discard(ws)
        if not self.rooms.get(user_id):
            self.rooms.pop(user_id, None)

    async def publish(self, user_id: int, message: dict) -> None:
        """Надсилає повідомлення всім з'єднанням користувача (усі його відкриті вкладки)."""
        async def send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(message), SEND_TIMEOUT_S)
            except Exception:  # клієнт зник або завис: прибираємо, решті події йдуть незалежно
                self.leave(user_id, ws)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ws.close(), SEND_TIMEOUT_S)

        # gather: усім одночасно, тож один повільний клієнт не затримує інших.
        await asyncio.gather(*(send(ws) for ws in list(self.rooms.get(user_id, ()))))


hub = Hub()  # єдиний екземпляр на весь процес


def publish_after_commit(db, user_id: int, message: dict) -> None:
    """Ставить подію в чергу сесії; відправиться після успішного коміту, при відкаті – зникне."""
    # session.info – довільний словник, що живе стільки ж, скільки сесія БД; зручне місце для черги подій.
    db.sync_session.info.setdefault("events", []).append((user_id, message))


@event.listens_for(Session, "after_commit")
def _flush_events(session: Session) -> None:
    """Слухач SQLAlchemy: транзакцію щойно успішно збережено -> можна розсилати накопичені події."""
    events = session.info.pop("events", None)
    if events:
        spawn(_send_all(events))  # відправка в окремій задачі, щоб не затримувати коміт


@event.listens_for(Session, "after_rollback")
def _drop_events(session: Session) -> None:
    """Слухач SQLAlchemy: транзакцію відкотили -> події недостовірні, відкидаємо їх."""
    session.info.pop("events", None)


async def _send_all(events: list[tuple[int, dict]]) -> None:
    """Послідовно розсилає накопичені події (порядок збережено)."""
    for user_id, message in events:
        await hub.publish(user_id, message)
