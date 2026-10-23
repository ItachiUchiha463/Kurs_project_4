import asyncio
import contextlib
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.errors import AuthError
from app.realtime.hub import hub
from app.security import Claims, decode_access_token
from app.services import auth as auth_service

router = APIRouter()
AUTH_TIMEOUT_S = 5
RECHECK_S = 30  # як часто перевіряємо, що токен усе ще чинний
_now = time.time  # підміняється в тестах


async def _still_valid(claims: Claims) -> bool:
    """Токен не прострочений, а користувача не заблоковано й сесії не скасовано (token_version)."""
    if _now() >= claims.exp:
        return False
    try:
        async with SessionLocal() as db:
            await auth_service.user_from_token(db, claims.user_id, claims.token_version)
    except AuthError:
        return False
    return True


async def _watch(ws: WebSocket, claims: Claims) -> None:
    """Закриває з'єднання, щойно токен втратив чинність: відкритий сокет не повинен жити довше за сесію."""
    while True:
        await asyncio.sleep(RECHECK_S)
        if not await _still_valid(claims):
            with contextlib.suppress(Exception):
                await ws.close(code=4401)
            return


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Токен не в URL (адреси потрапляють у журнали проксі): клієнт першим повідомленням надсилає {"type":"auth","token":…}."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_S)
        claims = decode_access_token(first.get("token", "")) if first.get("type") == "auth" else None
        if not claims:
            raise AuthError()
        async with SessionLocal() as db:
            user = await auth_service.user_from_token(db, claims.user_id, claims.token_version)
    except (asyncio.TimeoutError, AuthError, ValueError, AttributeError, WebSocketDisconnect, KeyError):
        await ws.close(code=4401)
        return
    hub.join(user.id, ws)
    watcher = asyncio.create_task(_watch(ws, claims))
    await ws.send_json({"type": "ready"})
    try:
        while True:
            if await ws.receive_text() == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        watcher.cancel()
        hub.leave(user.id, ws)
