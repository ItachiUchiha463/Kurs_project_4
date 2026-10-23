"""WebSocket-хаб (ТЗ 10.1): «кімнати» за user_id, тож подія одного користувача не потрапляє іншому.

Події публікуються лише після коміту транзакції, інакше клієнт міг би побачити інцидент, якого потім не існує.
"""
import asyncio
import contextlib
import logging

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.tasks import spawn

log = logging.getLogger("vigil.realtime")
SEND_TIMEOUT_S = 2


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = {}

    def join(self, user_id: int, ws: WebSocket) -> None:
        self.rooms.setdefault(user_id, set()).add(ws)

    def leave(self, user_id: int, ws: WebSocket) -> None:
        self.rooms.get(user_id, set()).discard(ws)
        if not self.rooms.get(user_id):
            self.rooms.pop(user_id, None)

    async def publish(self, user_id: int, message: dict) -> None:
        async def send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(message), SEND_TIMEOUT_S)
            except Exception:  # клієнт зник або завис: прибираємо, решті події йдуть незалежно
                self.leave(user_id, ws)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ws.close(), SEND_TIMEOUT_S)

        await asyncio.gather(*(send(ws) for ws in list(self.rooms.get(user_id, ()))))


hub = Hub()


def publish_after_commit(db, user_id: int, message: dict) -> None:
    """Ставить подію в чергу сесії; відправиться після успішного коміту, при відкаті – зникне."""
    db.sync_session.info.setdefault("events", []).append((user_id, message))


@event.listens_for(Session, "after_commit")
def _flush_events(session: Session) -> None:
    events = session.info.pop("events", None)
    if events:
        spawn(_send_all(events))


@event.listens_for(Session, "after_rollback")
def _drop_events(session: Session) -> None:
    session.info.pop("events", None)


async def _send_all(events: list[tuple[int, dict]]) -> None:
    for user_id, message in events:
        await hub.publish(user_id, message)
