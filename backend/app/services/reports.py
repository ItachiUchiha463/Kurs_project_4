"""Звіт за період (ТЗ розд. 12): доступність, інциденти, час виявлення й відновлення, середні та пікові значення метрик."""
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import AVAILABILITY_METRICS
from app.errors import Unprocessable
from app.models import Diagnosis, Incident, Rule, Target, User
from app.schemas.reports import MetricStat, ReportOut, ReportRow, TopCause

MAX_PERIOD = timedelta(days=31)  # сирі дані зберігаються 30 днів
# які метрики показуємо в звіті для кожного типу об'єкта
REPORT_METRICS = {
    "server": ["cpu_usage", "ram_usage"], "service": ["response_ms"],
    "container": ["container_cpu", "container_mem"], "database": ["db_connections_pct"],
}
COLUMN_METRICS = ["cpu_usage", "ram_usage", "response_ms", "container_cpu", "container_mem", "db_connections_pct"]
LABELS = {"cpu_usage": "CPU", "ram_usage": "RAM", "response_ms": "Час відповіді, мс", "container_cpu": "CPU контейнера",
          "container_mem": "RAM контейнера", "db_connections_pct": "З'єднання БД, %"}
TYPES = {"server": "Сервер", "service": "Сервіс", "container": "Контейнер", "database": "База даних"}


def _check_period(start: datetime, end: datetime) -> None:
    if end <= start:
        raise Unprocessable("Кінець періоду має бути пізніше за початок")
    if end - start > MAX_PERIOD:
        raise Unprocessable("Звіт можна побудувати не більше ніж за 31 день")


async def _metric_stats(db: AsyncSession, ids: list[int], names: list[str], start: datetime, end: datetime) -> dict[tuple[int, str], MetricStat]:
    """Середнє й максимум; період понад добу береться з агрегату metrics_5m (максимум – максимум максимумів)."""
    if not ids:
        return {}
    long = end - start > timedelta(hours=24)
    sql = ("SELECT target_id, name, avg(avg_value), max(max_value) FROM metrics_5m WHERE bucket >= :s AND bucket < :e"
           if long else "SELECT target_id, name, avg(value), max(value) FROM metrics WHERE ts >= :s AND ts < :e")
    rows = await db.execute(text(sql + " AND target_id = ANY(:ids) AND name = ANY(:names) AND instance = '' GROUP BY target_id, name"),
                            {"s": start, "e": end, "ids": ids, "names": names})
    return {(t, n): MetricStat(avg=a, max=m) for t, n, a, m in rows}


def _overlap_s(inc: Incident, start: datetime, end: datetime, now: datetime) -> float:
    lo, hi = max(inc.started_at, start), min(inc.resolved_at or now, end)
    return max((hi - lo).total_seconds(), 0.0)


async def build(db: AsyncSession, user: User, start: datetime, end: datetime) -> ReportOut:
    _check_period(start, end)
    now = datetime.now(timezone.utc)
    targets = list(await db.scalars(select(Target).where(Target.owner_id == user.id, Target.hidden.is_(False)).order_by(Target.id)))
    incidents = list(await db.scalars(select(Incident).where(
        Incident.owner_id == user.id, Incident.started_at < end, (Incident.resolved_at.is_(None)) | (Incident.resolved_at > start))))
    by_target: dict[int, list[Incident]] = defaultdict(list)
    for i in incidents:
        by_target[i.target_id].append(i)
    names = sorted({n for t in targets for n in REPORT_METRICS.get(t.type, [])})
    stats = await _metric_stats(db, [t.id for t in targets], names, start, end)

    rows = []
    for t in targets:
        mine = by_target[t.id]
        observed = max((end - max(start, t.created_at)).total_seconds(), 1.0)  # об'єкт, доданий посеред періоду, не «недоступний» до створення
        down = sum(_overlap_s(i, start, end, now) for i in mine if i.metric in AVAILABILITY_METRICS)
        started = [i for i in mine if start <= i.started_at < end]
        detect = [(i.started_at - i.first_breach_at).total_seconds() for i in started if i.first_breach_at]
        recover = [(i.resolved_at - i.started_at).total_seconds() for i in started if i.resolved_at and i.status == "resolved"]
        rows.append(ReportRow(
            target_id=t.id, name=t.name, type=t.type, availability_pct=round(max(0.0, 100 * (1 - down / observed)), 3),
            incidents=len(started), warning=sum(i.severity == "warning" for i in started), critical=sum(i.severity == "critical" for i in started),
            mean_detect_s=sum(detect) / len(detect) if detect else None, mean_recover_s=sum(recover) / len(recover) if recover else None,
            metrics={n: stats[(t.id, n)] for n in REPORT_METRICS.get(t.type, []) if (t.id, n) in stats}))

    causes = await db.execute(select(Rule.cause, text("count(*) AS n")).select_from(Diagnosis)
                              .join(Incident, Incident.id == Diagnosis.incident_id).join(Rule, Rule.id == Diagnosis.rule_id)
                              .where(Incident.owner_id == user.id, Incident.started_at >= start, Incident.started_at < end)
                              .group_by(Rule.cause).order_by(text("n DESC")).limit(5))
    return ReportOut(start=start, end=end, rows=rows, top_causes=[TopCause(cause=c, count=n) for c, n in causes],
                     incidents=sum(r.incidents for r in rows), critical=sum(r.critical for r in rows))


def to_csv(report: ReportOut) -> str:
    """CSV для Excel: роздільник «;», кодування UTF-8 з BOM додає маршрут."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Об'єкт", "Тип", "Доступність, %", "Інцидентів", "Попереджень", "Критичних", "Сер. виявлення, с", "Сер. відновлення, с",
                *[f"{LABELS[m]} (сер.)" for m in COLUMN_METRICS], *[f"{LABELS[m]} (макс.)" for m in COLUMN_METRICS]])
    fmt = lambda v: "" if v is None else f"{v:.1f}"  # noqa: E731
    for r in report.rows:
        w.writerow([r.name, TYPES.get(r.type, r.type), r.availability_pct, r.incidents, r.warning, r.critical, fmt(r.mean_detect_s),
                    fmt(r.mean_recover_s), *[fmt(r.metrics[m].avg) if m in r.metrics else "" for m in COLUMN_METRICS],
                    *[fmt(r.metrics[m].max) if m in r.metrics else "" for m in COLUMN_METRICS]])
    return out.getvalue()
