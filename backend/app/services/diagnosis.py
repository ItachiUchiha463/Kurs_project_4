"""Збір фактів для рушія виведення й збереження діагнозу (ТЗ розд. 8.2)."""
from datetime import datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import inference
from app.engine.inference import Condition
from app.models import Diagnosis, Incident, Rule, Target

NO_CAUSE = "Причину не визначено"
NO_CAUSE_HINT = "Перегляньте графіки метрик за час інциденту."
LAST_LOOKBACK = timedelta(minutes=15)


def to_engine_rule(r: Rule) -> inference.Rule:
    return inference.Rule(r.id, r.name, r.cause, r.recommendation, tuple(r.applies_to),
                          tuple(Condition(**c) for c in r.conditions), r.priority, own=r.owner_id is not None)


async def _fact(db: AsyncSession, target_id: int, c: Condition, incident_instance: str, ref: datetime) -> float | None:
    params = {"t": target_id, "n": c.metric, "ref": ref}
    inst = ""
    if c.instance == "same":
        inst = incident_instance
    where_inst = "" if c.instance == "any" else "AND instance = :i"
    if c.instance != "any":
        params["i"] = inst
    if c.agg == "last":
        params["since"] = ref - LAST_LOOKBACK
        sql = f"""SELECT max(v) FROM (SELECT DISTINCT ON (instance) value AS v FROM metrics
                  WHERE target_id = :t AND name = :n {where_inst} AND ts <= :ref AND ts > :since
                  ORDER BY instance, ts DESC) x"""
    else:
        params["since"] = ref - timedelta(seconds=c.window_s)
        sql = f"""SELECT {c.agg}(value) FROM metrics
                  WHERE target_id = :t AND name = :n {where_inst} AND ts <= :ref AND ts > :since"""
    return (await db.execute(text(sql), params)).scalar()


async def host_of(db: AsyncSession, target: Target) -> Target | None:
    if target.type == "server":
        return target
    if target.host_id is None:
        return None
    return await db.scalar(select(Target).where(Target.id == target.host_id, Target.owner_id == target.owner_id))


async def diagnose_incident(db: AsyncSession, incident: Incident, target: Target, ref: datetime) -> Diagnosis:
    rows = await db.scalars(select(Rule).where(Rule.enabled, or_(Rule.owner_id.is_(None), Rule.owner_id == target.owner_id)))
    rules = [to_engine_rule(r) for r in rows if target.type in r.applies_to]
    host = await host_of(db, target)
    subjects = {"self": target, "host": host}
    facts: dict[tuple, float | None] = {}
    for rule in rules:
        for c in rule.conditions:
            if c.fact_key in facts:
                continue
            subject = subjects[c.scope]
            facts[c.fact_key] = await _fact(db, subject.id, c, incident.instance, ref) if subject else None
    names = {"self": target.name, "host": host.name if host else "–"}
    result = inference.diagnose(rules, facts, names, target.type)

    primary = result.primary
    diagnosis = await db.scalar(select(Diagnosis).where(Diagnosis.incident_id == incident.id))
    if diagnosis is None:
        diagnosis = Diagnosis(incident_id=incident.id)
        db.add(diagnosis)
    diagnosis.rule_id = primary.rule.id if primary else None
    diagnosis.matched_ratio = primary.ratio if primary else 0.0
    diagnosis.evidence = [vars(e) for e in primary.evidence] if primary else []
    diagnosis.alternatives = [{"name": m.rule.cause, "ok": sum(e.ok for e in m.evidence), "total": len(m.evidence)}
                              for m in result.alternatives[:3]]
    return diagnosis
