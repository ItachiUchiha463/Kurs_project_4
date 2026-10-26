from datetime import datetime, timedelta, timezone

import asyncpg

from app.db import SessionLocal
from app.repositories import metrics as metrics_repo
from tests.conftest import TEST_URL, _dsn
from tests.test_incidents import server


async def refresh_aggregate():
    """Безперервний агрегат оновлюється фоновою політикою; у тесті – вручну (команда не працює в транзакції)."""
    conn = await asyncpg.connect(_dsn(TEST_URL, "vigil_test"))
    try:
        await conn.execute("CALL refresh_continuous_aggregate('metrics_5m', NULL, NULL)")
    finally:
        await conn.close()


async def test_long_range_is_served_from_the_5_minute_aggregate(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base = now.replace(minute=now.minute // 5 * 5) - timedelta(days=3)  # початок 5-хвилинного вікна 3 дні тому
    rows = [{"target_id": srv["id"], "name": "cpu_usage", "instance": "", "value": float(v), "ts": base + timedelta(minutes=m)}
            for m, v in ((1, 10), (2, 20), (3, 30))]  # три точки в одному вікні
    async with SessionLocal() as db:
        await metrics_repo.insert_many(db, rows)
        await db.commit()
    await refresh_aggregate()
    start, end = now - timedelta(days=7), now
    r = await client.get(f"/api/targets/{srv['id']}/metrics", params={"name": "cpu_usage", "from": start.isoformat(), "to": end.isoformat()},
                         headers=h)
    points = r.json()
    assert r.status_code == 200 and len(points) == 1 and abs(points[0]["value"] - 20) < 0.001  # середнє трьох значень


async def test_short_range_still_reads_raw_data(client, user_factory):
    h = await user_factory()
    srv = await server(client, h)
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        await metrics_repo.insert_many(db, [{"target_id": srv["id"], "name": "cpu_usage", "instance": "", "value": 42.0, "ts": now - timedelta(minutes=5)}])
        await db.commit()
    r = await client.get(f"/api/targets/{srv['id']}/metrics", params={"name": "cpu_usage", "from": (now - timedelta(hours=1)).isoformat(),
                                                                       "to": now.isoformat()}, headers=h)
    assert [p["value"] for p in r.json()] == [42.0]  # без refresh агрегату: сирі дані видно одразу


async def test_aggregate_and_compression_policies_exist():
    conn = await asyncpg.connect(_dsn(TEST_URL, "vigil_test"))
    try:
        jobs = {r["proc_name"] for r in await conn.fetch("SELECT proc_name FROM timescaledb_information.jobs")}
    finally:
        await conn.close()
    assert {"policy_refresh_continuous_aggregate", "policy_compression", "policy_retention"} <= jobs
