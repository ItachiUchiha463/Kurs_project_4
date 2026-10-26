from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import SERVER_AVAILABILITY
from app.errors import Conflict, NotFound
from app.models import Incident, Target, User
from app.repositories import incidents as repo
from app.schemas.incidents import DiagnosisOut, EventOut, IncidentDetail, IncidentOut
from app.realtime.hub import publish_after_commit
from app.services import events, pipeline
from app.services.diagnosis import NO_CAUSE, NO_CAUSE_HINT


def _out(inc: Incident, target_name: str, suppressed_count: int = 0) -> IncidentOut:
    out = IncidentOut.model_validate(inc)
    out.target_name = target_name
    out.suppressed_count = suppressed_count
    return out


async def list_incidents(db: AsyncSession, user: User, status: str | None, target_id: int | None,
                         severity: str | None, cursor: int | None, limit: int) -> list[IncidentOut]:
    rows = await repo.list_for_owner(db, user.id, status, target_id, severity, cursor, limit)
    counts = await repo.suppressed_counts(db, [i.id for i, _ in rows])
    return [_out(i, name, counts.get(i.id, 0)) for i, name in rows]


async def _get(db: AsyncSession, user: User, incident_id: int) -> tuple[Incident, str]:
    row = await repo.get(db, user.id, incident_id)
    if not row:
        raise NotFound("Інцидент не знайдено")
    return row


async def get_incident(db: AsyncSession, user: User, incident_id: int) -> IncidentDetail:
    inc, name = await _get(db, user, incident_id)
    events = [EventOut.model_validate(e) for e in await repo.events(db, inc.id)]
    diagnosis = await repo.diagnosis(db, inc.id)
    related = [_out(i, n) for i, n in await repo.suppressed_of(db, inc.id)]
    return IncidentDetail(**_out(inc, name, sum(i.status == "suppressed" for i in related)).model_dump(), events=events, diagnosis=diagnosis_out(diagnosis),
                          related=related)


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
    pipeline.keep_silent(inc)
    if inc.metric in SERVER_AVAILABILITY:  # закрили вручну: придушені дочірні об'єкти теж звільняються
        await pipeline.release(db, inc.target_id, inc.resolved_at)
    await pipeline.refresh_status(db, await db.get(Target, inc.target_id))
    publish_after_commit(db, user.id, events.incident_event(inc, name, "resolved"))
    return _out(inc, name)
