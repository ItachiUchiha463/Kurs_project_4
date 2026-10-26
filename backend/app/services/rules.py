"""Правила логічного виведення: перегляд, власні правила користувача, вмикання базових і перевірка на поточних даних (ТЗ 8, 10)."""
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.engine import inference
from app.errors import NotFound, QuotaExceeded, Unprocessable
from app.models import Rule, RuleOverride, Target, User
from app.schemas.rules import RuleIn, RuleOut, RuleTestOut
from app.services import diagnosis


def _out(rule: Rule, enabled: bool) -> RuleOut:
    return RuleOut(id=rule.id, name=rule.name, cause=rule.cause, recommendation=rule.recommendation, applies_to=list(rule.applies_to),
                   conditions=rule.conditions, priority=rule.priority, enabled=enabled, own=rule.owner_id is not None)


async def _visible(db: AsyncSession, user: User, rule_id: int) -> tuple[Rule, bool | None]:
    """Правило, яке користувач бачить (базове або своє), і його вимикання (None – без перевизначення)."""
    row = (await db.execute(select(Rule, RuleOverride.enabled).outerjoin(
        RuleOverride, and_(RuleOverride.rule_id == Rule.id, RuleOverride.owner_id == user.id))
        .where(Rule.id == rule_id, or_(Rule.owner_id.is_(None), Rule.owner_id == user.id)))).first()
    if row is None:
        raise NotFound("Правило не знайдено")
    return row[0], row[1]


async def _own(db: AsyncSession, user: User, rule_id: int) -> Rule:
    rule = await db.scalar(select(Rule).where(Rule.id == rule_id, Rule.owner_id == user.id))
    if rule is None:
        raise NotFound("Власне правило не знайдено")  # базові правила змінювати не можна: їх лише вмикають і вимикають
    return rule


async def list_rules(db: AsyncSession, user: User) -> list[RuleOut]:
    rows = await db.execute(select(Rule, RuleOverride.enabled).outerjoin(
        RuleOverride, and_(RuleOverride.rule_id == Rule.id, RuleOverride.owner_id == user.id))
        .where(or_(Rule.owner_id.is_(None), Rule.owner_id == user.id)).order_by(Rule.owner_id.is_(None).desc(), Rule.id))
    return [_out(r, r.enabled if o is None else o) for r, o in rows]


def _fill(rule: Rule, data: RuleIn) -> None:
    rule.name, rule.cause, rule.recommendation, rule.priority = data.name, data.cause, data.recommendation, data.priority
    rule.applies_to = list(data.applies_to)
    rule.conditions = [c.model_dump() for c in data.conditions]


async def create(db: AsyncSession, user: User, data: RuleIn) -> RuleOut:
    if await db.scalar(select(func.count()).select_from(Rule).where(Rule.owner_id == user.id)) >= settings.quota_rules:
        raise QuotaExceeded(f"Ліміт власних правил: {settings.quota_rules}")
    rule = Rule(owner_id=user.id, enabled=True)
    _fill(rule, data)
    db.add(rule)
    await db.flush()
    return _out(rule, True)


async def update(db: AsyncSession, user: User, rule_id: int, data: RuleIn) -> RuleOut:
    rule = await _own(db, user, rule_id)
    _fill(rule, data)
    return _out(rule, rule.enabled)


async def remove(db: AsyncSession, user: User, rule_id: int) -> None:
    await _own(db, user, rule_id)
    await db.execute(delete(Rule).where(Rule.id == rule_id))


async def set_enabled(db: AsyncSession, user: User, rule_id: int, enabled: bool) -> RuleOut:
    rule, override = await _visible(db, user, rule_id)
    if rule.owner_id is not None:
        rule.enabled = enabled
    else:  # базове правило однакове для всіх, тож вимикається лише для цього користувача
        row = await db.get(RuleOverride, (user.id, rule_id))
        if row is None:
            db.add(RuleOverride(owner_id=user.id, rule_id=rule_id, enabled=enabled))
        else:
            row.enabled = enabled
    return _out(rule, enabled)


async def test(db: AsyncSession, user: User, rule_id: int, target_id: int) -> RuleTestOut:
    """Чи спрацювало б правило на поточних даних об'єкта (без інциденту), з поясненням за кожною умовою."""
    rule, _ = await _visible(db, user, rule_id)
    target = await db.scalar(select(Target).where(Target.id == target_id, Target.owner_id == user.id))
    if target is None:
        raise NotFound("Об'єкт не знайдено")
    if target.type not in rule.applies_to:
        raise Unprocessable("Правило не стосується цього типу об'єкта", details=[{"field": "target_id", "message": "Інший тип об'єкта"}])
    engine_rule = diagnosis.to_engine_rule(rule)
    facts, names = await diagnosis.collect_facts(db, target, [engine_rule], "", datetime.now(timezone.utc))
    match = inference.evaluate(engine_rule, facts, names)
    return RuleTestOut(ratio=match.ratio, matched=match.ratio == 1.0, evidence=[vars(e) for e in match.evidence])
