"""Фонові задачі в одному процесі (ТЗ розд. 3): планувальник перевірок і контроль агентів.

Рівно один процес: перед стартом береться advisory lock PostgreSQL; другий процес його не отримає й лише обслуговує HTTP.
"""
import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.models import Target
from app.notify import outbox, telegram
from app.notify.commands import handle_update
from app.services import checks

log = logging.getLogger("vigil.background")
LOCK_KEY = 7_201_026  # довільне число, спільне для всіх екземплярів Vigil на одній БД
TICK_S = 5
LIVENESS_S = 15
GLOBAL_LIMIT, OWNER_LIMIT = 50, 5  # одночасних перевірок на весь сервіс і на одного користувача (ТЗ 5.2)

beats: dict[str, float] = {}   # назва задачі → час останнього циклу (monotonic) для /health
started = False
_next_run: dict[int, float] = {}
_running: set[int] = set()
_global = asyncio.Semaphore(GLOBAL_LIMIT)
_per_owner: dict[int, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(OWNER_LIMIT))


async def _check_one(target_id: int, owner_id: int, checker) -> None:
    async with _global, _per_owner[owner_id]:
        try:
            async with SessionLocal() as db:
                target = await db.get(Target, target_id)
                if target and target.enabled:
                    await checks.run_http_check(db, target, checker)
                    await db.commit()
        except Exception:  # збій однієї перевірки не зупиняє інші
            log.exception("збій перевірки", extra={"target_id": target_id})
        finally:
            _running.discard(target_id)


async def schedule_due(checker=None, now: float | None = None) -> int:
    """Запускає перевірки, час яких настав; повертає, скільки запущено."""
    now = time.monotonic() if now is None else now
    async with SessionLocal() as db:
        rows = (await db.execute(select(Target.id, Target.owner_id, Target.interval_s)
                                 .where(Target.check_type == "http", Target.enabled))).all()
    launched = 0
    for tid, owner, interval in rows:
        if tid in _running or _next_run.get(tid, 0) > now:
            continue
        _next_run[tid] = now + interval
        _running.add(tid)
        asyncio.create_task(_check_one(tid, owner, checker))
        launched += 1
    return launched


async def _scheduler_loop() -> None:
    while True:
        try:
            await schedule_due()
            beats["scheduler"] = time.monotonic()
        except Exception:
            log.exception("збій планувальника")
        await asyncio.sleep(TICK_S)


async def _notify_loop() -> None:
    while True:
        try:
            if bot := telegram.get_bot():
                async with SessionLocal() as db:
                    await outbox.deliver_pending(db, bot)
            beats["notify"] = time.monotonic()
        except Exception:
            log.exception("збій відправки сповіщень")
        await asyncio.sleep(2)


async def _bot_loop() -> None:
    """Long polling (ТЗ 9.1): працює і без публічної HTTPS-адреси."""
    offset = 0
    while True:
        bot = telegram.get_bot()
        if not bot:
            beats["bot"] = time.monotonic()
            await asyncio.sleep(30)
            continue
        try:
            for update in await bot.updates(offset):
                offset = update["update_id"] + 1
                async with SessionLocal() as db:
                    await handle_update(db, bot, update)
                    await db.commit()
            beats["bot"] = time.monotonic()
        except Exception as e:  # мережа, 409 від другого getUpdates тощо – не зупиняємо задачу
            log.warning("збій бота: %s", type(e).__name__)
            beats["bot"] = time.monotonic()
            await asyncio.sleep(5)


async def _liveness_loop() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await checks.check_agents(db)
                await db.commit()
            beats["liveness"] = time.monotonic()
        except Exception:
            log.exception("збій контролю агентів")
        await asyncio.sleep(LIVENESS_S)


class Background:
    """Тримає lock і задачі від старту до зупинки застосунку."""

    def __init__(self) -> None:
        self._conn = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> bool:
        global started
        self._conn = await engine.connect()
        await self._conn.execution_options(isolation_level="AUTOCOMMIT")
        got = (await self._conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
        if not got:
            log.warning("фонові задачі вже працюють в іншому процесі; цей лише обслуговує HTTP")
            await self._conn.close()
            self._conn = None
            return False
        beats.update({k: time.monotonic() for k in ('scheduler', 'liveness', 'notify', 'bot')})
        self._tasks = [asyncio.create_task(f()) for f in (_scheduler_loop, _liveness_loop, _notify_loop, _bot_loop)]
        started = True
        log.info("фонові задачі запущено")
        return True

    async def stop(self) -> None:
        global started
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._conn:
            await self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await self._conn.close()
        started = False


def health(now: float | None = None) -> dict:
    """Серцебиття фонових задач (ТЗ 16.1): якщо задача мовчить понад 2 хв, /health повертає 503."""
    now = time.monotonic() if now is None else now
    if not started:
        return {"background": "off", "ok": True}
    stale = [name for name, t in beats.items() if now - t > 120]
    return {"background": "stale" if stale else "ok", "stale": stale, "ok": not stale}
