from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import background
from app.deps import DbDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep):
    """Для зовнішнього монітора (ТЗ 16.1): 503, якщо недоступна БД або фонові задачі «заснули»."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"ok": False, "db": "down"}, status_code=503)
    state = background.health()
    return JSONResponse({"db": "ok", **state}, status_code=200 if state["ok"] else 503)
