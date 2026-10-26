"""Усі вибірки приймають owner_id. add/get_open без owner_id викликає лише конвеєр, що вже має перевірений об'єкт."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.engine.defaults import SERVER_AVAILABILITY
from app.models import Diagnosis, Incident, IncidentEvent, Rule, Target

LIVE = ("open", "acknowledged")
UNRESOLVED = LIVE + ("suppressed",)  # відповідає частковому унікальному індексу one_open_incident (status <> 'resolved')


async def list_for_owner(db: AsyncSession, owner_id: int, status: str | None, target_id: int | None,
                         severity: str | None, cursor: int | None, limit: int) -> list[tuple[Incident, str]]:
    q = (select(Incident, Target.name).join(Target, Target.id == Incident.target_id)
         .where(Incident.owner_id == owner_id).order_by(Incident.id.desc()).limit(limit))
    if status == "active":
        q = q.where(Incident.status.in_(LIVE))
    elif status:
        q = q.where(Incident.status == status)
    else:
        q = q.where(Incident.status != "suppressed")  # придушені показуються згорнутими під інцидентом сервера
    if target_id:
        q = q.where(Incident.target_id == target_id)
    if severity:
        q = q.where(Incident.severity == severity)
    if cursor:
        q = q.where(Incident.id < cursor)
    return [(i, n) for i, n in await db.execute(q)]


async def get(db: AsyncSession, owner_id: int, incident_id: int) -> tuple[Incident, str] | None:
    row = (await db.execute(select(Incident, Target.name).join(Target, Target.id == Incident.target_id)
                            .where(Incident.id == incident_id, Incident.owner_id == owner_id))).first()
    return (row[0], row[1]) if row else None


async def events(db: AsyncSession, incident_id: int) -> list[IncidentEvent]:
    return list(await db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == incident_id)
                                 .order_by(IncidentEvent.ts, IncidentEvent.id)))


async def diagnosis(db: AsyncSession, incident_id: int) -> tuple[Diagnosis, Rule | None] | None:
    row = (await db.execute(select(Diagnosis, Rule).outerjoin(Rule, Rule.id == Diagnosis.rule_id)
                            .where(Diagnosis.incident_id == incident_id))).first()
    return (row[0], row[1]) if row else None


async def get_live(db: AsyncSession, target_id: int, metric: str, instance: str) -> Incident | None:
    return await db.scalar(select(Incident).where(
        Incident.target_id == target_id, Incident.metric == metric, Incident.instance == instance,
        Incident.status.in_(UNRESOLVED)))


async def live_for_target(db: AsyncSession, target_id: int) -> list[Incident]:
    return list(await db.scalars(select(Incident).where(Incident.target_id == target_id, Incident.status.in_(LIVE))))


def add_event(db: AsyncSession, incident_id: int, type_: str, value=None, ts=None, user_id=None, note=None) -> None:
    ev = IncidentEvent(incident_id=incident_id, type=type_, value=value, user_id=user_id, note=note)
    if ts is not None:
        ev.ts = ts
    db.add(ev)


async def server_down(db: AsyncSession, server_id: int) -> Incident | None:
    """Відкритий інцидент недоступності сервера (agent_alive або ping_available), якщо є."""
    return await db.scalar(select(Incident).where(
        Incident.target_id == server_id, Incident.metric.in_(SERVER_AVAILABILITY), Incident.status.in_(LIVE)).order_by(Incident.id).limit(1))


async def suppressed_counts(db: AsyncSession, incident_ids: list[int]) -> dict[int, int]:
    if not incident_ids:
        return {}
    rows = await db.execute(select(Incident.suppressed_by, func.count()).where(
        Incident.suppressed_by.in_(incident_ids), Incident.status == "suppressed").group_by(Incident.suppressed_by))
    return dict(rows.all())


async def suppressed_of(db: AsyncSession, incident_id: int) -> list[tuple[Incident, str]]:
    rows = await db.execute(select(Incident, Target.name).join(Target, Target.id == Incident.target_id).where(
        Incident.suppressed_by == incident_id).order_by(Incident.id))
    return [(i, n) for i, n in rows]
