from datetime import timedelta

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Diagnosis, Incident, Rule
from app.repositories import metrics as metrics_repo
from tests.helpers import now
from tests.test_incidents import server


async def aged_server(client, h, name="web-01"):
    srv = await server(client, h, name)
    async with SessionLocal() as db:
        await db.execute(text("UPDATE targets SET created_at = now() - interval '30 days'"))
        await db.commit()
    return srv


async def add_incident(owner_id, target_id, metric, severity, started, resolved, breach):
    async with SessionLocal() as db:
        inc = Incident(owner_id=owner_id, target_id=target_id, metric=metric, severity=severity,
                       status="resolved" if resolved else "open", started_at=started, resolved_at=resolved, first_breach_at=breach)
        db.add(inc)
        await db.commit()
        return inc.id


def params(hours=10):
    end = now()
    return {"from": (end - timedelta(hours=hours)).isoformat(), "to": end.isoformat()}


async def me_id(client, h):
    return (await client.get("/api/me", headers=h)).json()["id"]


async def test_report_counts_availability_and_times(client, user_factory):
    h = await user_factory()
    srv = await aged_server(client, h)
    owner = await me_id(client, h)
    t = now()
    # година недоступності всередині періоду + критичний інцидент CPU, що тривав 30 хв і виявлений через 2 хв
    await add_incident(owner, srv["id"], "agent_alive", "critical", t - timedelta(hours=5), t - timedelta(hours=4), t - timedelta(hours=5))
    await add_incident(owner, srv["id"], "cpu_usage", "warning", t - timedelta(hours=3), t - timedelta(hours=2, minutes=30), t - timedelta(hours=3, minutes=2))
    rep = (await client.get("/api/reports", params=params(10), headers=h)).json()
    [row] = rep["rows"]
    assert row["name"] == "web-01" and row["incidents"] == 2 and row["critical"] == 1 and row["warning"] == 1
    assert abs(row["availability_pct"] - 90.0) < 0.1  # 1 год із 10
    assert abs(row["mean_detect_s"] - 60.0) < 1  # (0 с і 120 с) / 2
    assert abs(row["mean_recover_s"] - (3600 + 1800) / 2) < 1
    assert rep["incidents"] == 2 and rep["critical"] == 1


async def test_incident_that_started_before_the_period_counts_only_its_overlap(client, user_factory):
    h = await user_factory()
    srv = await aged_server(client, h)
    owner = await me_id(client, h)
    t = now()
    await add_incident(owner, srv["id"], "agent_alive", "critical", t - timedelta(hours=20), t - timedelta(hours=8), t - timedelta(hours=20))
    row = (await client.get("/api/reports", params=params(10), headers=h)).json()["rows"][0]
    assert abs(row["availability_pct"] - 80.0) < 0.1  # 2 год із 10 лежать у періоді
    assert row["incidents"] == 0  # розпочався до періоду: у «кількість» не входить


async def test_open_incident_counts_until_end_of_period(client, user_factory):
    h = await user_factory()
    srv = await aged_server(client, h)
    owner = await me_id(client, h)
    await add_incident(owner, srv["id"], "ping_available", "critical", now() - timedelta(hours=2), None, None)
    row = (await client.get("/api/reports", params=params(10), headers=h)).json()["rows"][0]
    assert abs(row["availability_pct"] - 80.0) < 0.5


async def test_metric_average_and_peak_and_top_causes(client, user_factory):
    h = await user_factory()
    srv = await aged_server(client, h)
    owner = await me_id(client, h)
    t = now()
    async with SessionLocal() as db:
        await metrics_repo.insert_many(db, [{"target_id": srv["id"], "name": "cpu_usage", "instance": "", "value": v, "ts": t - timedelta(hours=1, minutes=m)}
                                            for m, v in ((0, 10.0), (1, 50.0))])
        await db.commit()
    inc = await add_incident(owner, srv["id"], "disk_usage", "critical", t - timedelta(hours=1), t - timedelta(minutes=30), None)
    async with SessionLocal() as db:
        rule = await db.scalar(select(Rule).where(Rule.name == "Заповнення диска"))
        db.add(Diagnosis(incident_id=inc, rule_id=rule.id, matched_ratio=1.0, evidence=[], alternatives=[]))
        await db.commit()
    rep = (await client.get("/api/reports", params=params(10), headers=h)).json()
    cpu = rep["rows"][0]["metrics"]["cpu_usage"]
    assert abs(cpu["avg"] - 30) < 0.01 and cpu["max"] == 50
    assert rep["top_causes"] == [{"cause": "Заповнення диска", "count": 1}]


async def test_csv_export(client, user_factory):
    h = await user_factory()
    await aged_server(client, h)
    r = await client.get("/api/reports", params={**params(10), "format": "csv"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8")
    assert body.startswith("﻿")  # BOM для Excel
    lines = body.lstrip("﻿").strip().splitlines()
    assert lines[0].split(";")[:4] == ["Об'єкт", "Тип", "Доступність, %", "Інцидентів"] and len(lines) == 2
    assert lines[1].startswith("web-01;Сервер;100.0;0;")


async def test_period_is_validated_and_users_are_isolated(client, user_factory):
    a = await user_factory(email="a@example.com")
    b = await user_factory(email="b@example.com")
    await aged_server(client, a)
    t = now()
    assert (await client.get("/api/reports", params={"from": t.isoformat(), "to": (t - timedelta(hours=1)).isoformat()}, headers=a)).status_code == 422
    assert (await client.get("/api/reports", params={"from": (t - timedelta(days=40)).isoformat(), "to": t.isoformat()}, headers=a)).status_code == 422
    assert (await client.get("/api/reports", params=params(10), headers=b)).json()["rows"] == []
    assert (await client.get("/api/reports")).status_code == 401
