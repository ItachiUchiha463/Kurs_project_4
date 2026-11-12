"""Збір фактів для рушія виведення й збереження діагнозу (ТЗ розд. 8.2)."""
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import inference
from app.engine.thresholds import AGG_SQL
from app.engine.inference import Condition
from app.models import Diagnosis, Incident, Rule, RuleOverride, Target

NO_CAUSE = "Причину не визначено"
NO_CAUSE_HINT = "Перегляньте графіки метрик за час інциденту."
LAST_LOOKBACK = timedelta(minutes=15)


def to_engine_rule(r: Rule) -> inference.Rule:
    return inference.Rule(r.id, r.name, r.cause, r.recommendation, tuple(r.applies_to),
                          tuple(Condition(**c) for c in r.conditions), r.priority, own=r.owner_id is not None)


async def _fact(db: AsyncSession, target_id: int, c: Condition, incident_instance: str, ref: datetime) -> float | None:
    params = {"t": target_id, "n": c.metric, "ref": ref}
    inst = incident_instance if c.instance == "same" else (c.instance or "")  # конкретне значення (наприклад, «/») береться як є
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
        sql = f"""SELECT {AGG_SQL[c.agg]} FROM metrics
                  WHERE target_id = :t AND name = :n {where_inst} AND ts <= :ref AND ts > :since"""
    return (await db.execute(text(sql), params)).scalar()


async def _sibling_values(db: AsyncSession, target: Target, c: Condition, incident_instance: str, ref: datetime) -> list[float]:
    """Значення метрики в усіх сусідніх об'єктів одного сервера (без самого об'єкта)."""
    if target.host_id is None:
        return []
    ids = await db.scalars(select(Target.id).where(
        Target.host_id == target.host_id, Target.owner_id == target.owner_id, Target.type == c.sibling_type,
        Target.id != target.id, Target.hidden.is_(False)))
    values = [await _fact(db, tid, c, incident_instance, ref) for tid in ids]
    return [v for v in values if v is not None]


async def host_of(db: AsyncSession, target: Target) -> Target | None:
    if target.type == "server":
        return target
    if target.host_id is None:
        return None
    return await db.scalar(select(Target).where(Target.id == target.host_id, Target.owner_id == target.owner_id))


async def active_rules(db: AsyncSession, owner_id: int, target_type: str) -> list[inference.Rule]:
    """Базові й власні правила, що діють для цього користувача: базові можна вимкнути (rule_overrides), власні – полем enabled."""
    rows = await db.execute(select(Rule, RuleOverride.enabled).outerjoin(
        RuleOverride, and_(RuleOverride.rule_id == Rule.id, RuleOverride.owner_id == owner_id))
        .where(or_(Rule.owner_id.is_(None), Rule.owner_id == owner_id)))
    return [to_engine_rule(r) for r, override in rows if (r.enabled if override is None else override) and target_type in r.applies_to]


async def collect_facts(db: AsyncSession, target: Target, rules: list[inference.Rule], incident_instance: str,
                        ref: datetime) -> tuple[dict[tuple, float | list[float] | None], dict[str, str]]:
    """Значення метрик для всіх умов правил: (факти, імена учасників для пояснення)."""
    host = await host_of(db, target)
    subjects = {"self": target, "host": host}
    facts: dict[tuple, float | list[float] | None] = {}
    for rule in rules:
        for c in rule.conditions:
            if c.fact_key in facts:
                continue
            if c.scope == "siblings":
                facts[c.fact_key] = await _sibling_values(db, target, c, incident_instance, ref)
                continue
            subject = subjects[c.scope]
            facts[c.fact_key] = await _fact(db, subject.id, c, incident_instance, ref) if subject else None
    return facts, {"self": target.name, "host": host.name if host else "–", "siblings": "на тому ж сервері"}


async def diagnose_incident(db: AsyncSession, incident: Incident, target: Target, ref: datetime) -> Diagnosis:
    rules = await active_rules(db, target.owner_id, target.type)
    facts, names = await collect_facts(db, target, rules, incident.instance, ref)
    result = inference.diagnose(rules, facts, names, target.type)

    primary = result.primary
    diagnosis = await db.scalar(select(Diagnosis).where(Diagnosis.incident_id == incident.id))
    if diagnosis is None:
        diagnosis = Diagnosis(incident_id=incident.id)
        db.add(diagnosis)
    diagnosis.rule_id = primary.rule.id if primary else None
    diagnosis.matched_ratio = primary.ratio if primary else 0.0
    diagnosis.evidence = [vars(e) for e in primary.evidence] if primary else []
    diagnosis.alternatives = [alternative(m) for m in result.alternatives[:3]]
    diagnosis.context = await context_notes(db, incident, target, ref)
    return diagnosis


def alternative(m: inference.Match) -> dict:
    """Можлива причина: відсоток збігу й умови, які не виконалися (відповідь на «чому не ця причина»)."""
    ok = sum(e.ok for e in m.evidence)
    return {"name": m.rule.cause, "ok": ok, "total": len(m.evidence), "pct": round(100 * m.ratio),
            "missing": [{"text": e.text, "value": e.value} for e in m.evidence if not e.ok]}


CONTEXT_WINDOW = timedelta(minutes=15)


async def context_notes(db: AsyncSession, incident: Incident, target: Target, ref: datetime) -> list[str]:
    """Що змінилося поруч перед збоєм: недавнє перезавантаження сервера й інциденти на тому ж сервері за 15 хв до цього."""
    host = await host_of(db, target)
    if host is None:
        return []
    notes: list[str] = []
    uptime = await db.scalar(text("""SELECT value FROM metrics WHERE target_id = :t AND name = 'uptime_h' AND instance = ''
                                     AND ts <= :ref AND ts > :since ORDER BY ts DESC LIMIT 1"""),
                             {"t": host.id, "ref": ref, "since": ref - LAST_LOOKBACK})
    if uptime is not None and uptime < 1:
        notes.append(f"Сервер «{host.name}» перезавантажено близько {max(1, round(uptime * 60))} хв тому")
    earlier = await db.execute(
        select(Incident, Target.name).join(Target, Target.id == Incident.target_id)
        .where(Incident.owner_id == target.owner_id, Incident.id != incident.id, or_(Target.id == host.id, Target.host_id == host.id),
               Incident.started_at < incident.started_at, Incident.started_at >= incident.started_at - CONTEXT_WINDOW)
        .order_by(Incident.started_at).limit(3))
    for other, name in earlier:
        label = inference.METRIC_LABELS.get(other.metric, other.metric) + (f" ({other.instance})" if other.instance else "")
        notes.append(f"За {max(1, round((incident.started_at - other.started_at).total_seconds() / 60))} хв до цього почався інцидент: «{name}: {label}»")
    return notes
