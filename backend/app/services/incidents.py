from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict, NotFound
from app.models import Incident, User
from app.repositories import incidents as repo
from app.schemas.incidents import DiagnosisOut, EventOut, IncidentDetail, IncidentOut
from app.realtime.hub import publish_after_commit
from app.services import events, pipeline
from app.services.diagnosis import NO_CAUSE, NO_CAUSE_HINT


def _out(inc: Incident, target_name: str) -> IncidentOut:
    out = IncidentOut.model_validate(inc)
    out.target_name = target_name
    return out


async def list_incidents(db: AsyncSession, user: User, status: str | None, target_id: int | None,
                         severity: str | None, cursor: int | None, limit: int) -> list[IncidentOut]:
    rows = await repo.list_for_owner(db, user.id, status, target_id, severity, cursor, limit)
    return [_out(i, name) for i, name in rows]


async def _get(db: AsyncSession, user: User, incident_id: int) -> tuple[Incident, str]:
    row = await repo.get(db, user.id, incident_id)
    if not row:
        raise NotFound("Інцидент не знайдено")
    return row


async def get_incident(db: AsyncSession, user: User, incident_id: int) -> IncidentDetail:
    inc, name = await _get(db, user, incident_id)
    events = [EventOut.model_validate(e) for e in await repo.events(db, inc.id)]
    diagnosis = await repo.diagnosis(db, inc.id)
    return IncidentDetail(**_out(inc, name).model_dump(), events=events, diagnosis=diagnosis_out(diagnosis))


def diagnosis_out(row) -> DiagnosisOut | None:
    if row is None:
        return None
    d, rule = row
    return DiagnosisOut(
        cause=rule.cause if rule else NO_CAUSE, recommendation=rule.recommendation if rule else NO_CAUSE_HINT,
        matched_ratio=d.matched_ratio, evidence=d.evidence, alternatives=d.alternatives)


async def acknowledge(db: AsyncSession, user: User, incident_id: int) -> IncidentOut:
    inc, name = await _get(db, user, incident_id)
    if inc.status != "open":
        raise Conflict("Підтвердити можна лише відкритий інцидент", code="invalid_state")
    inc.status, inc.acknowledged_at = "acknowledged", datetime.now(timezone.utc)
    repo.add_event(db, inc.id, "acknowledged", user_id=user.id)
    publish_after_commit(db, user.id, events.incident_event(inc, name, "acknowledged"))
    return _out(inc, name)


async def resolve(db: AsyncSession, user: User, incident_id: int, comment: str) -> IncidentOut:
    inc, name = await _get(db, user, incident_id)
    if inc.status not in repo.LIVE:
        raise Conflict("Інцидент уже закрито", code="invalid_state")
    inc.status, inc.resolved_at, inc.resolve_comment = "resolved", datetime.now(timezone.utc), comment.strip()
    repo.add_event(db, inc.id, "resolved", user_id=user.id, note=f"Закрито вручну: {inc.resolve_comment}")
    pipeline.forget(inc.target_id, inc.metric, inc.instance)
    publish_after_commit(db, user.id, events.incident_event(inc, name, "resolved"))
    return _out(inc, name)
