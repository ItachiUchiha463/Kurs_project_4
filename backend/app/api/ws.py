import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.errors import AuthError
from app.realtime.hub import hub
from app.security import decode_access_token
from app.services import auth as auth_service

router = APIRouter()
AUTH_TIMEOUT_S = 5


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Токен не в URL (адреси потрапляють у журнали проксі): клієнт першим повідомленням надсилає {"type":"auth","token":…}."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_S)
        parsed = decode_access_token(first.get("token", "")) if first.get("type") == "auth" else None
        if not parsed:
            raise AuthError()
        async with SessionLocal() as db:
            user = await auth_service.user_from_token(db, *parsed)
    except (asyncio.TimeoutError, AuthError, ValueError, AttributeError, WebSocketDisconnect, KeyError):
        await ws.close(code=4401)
        return
    hub.join(user.id, ws)
    await ws.send_json({"type": "ready"})
    try:
        while True:
            if await ws.receive_text() == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(user.id, ws)
