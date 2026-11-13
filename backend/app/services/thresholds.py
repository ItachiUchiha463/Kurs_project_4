"""Пороги з урахуванням власних налаштувань (ТЗ 7.3): поріг об'єкта > шаблон користувача > системний типовий.

Звідки береться поріг для метрики (від найпріоритетнішого):
  1. поріг, заданий користувачем саме для цього об'єкта («target»);
  2. шаблон користувача для всіх його об'єктів («template», target_id порожній);
  3. системний типовий (engine/defaults.py, «default»).
Користувач змінює лише рівні (warn, crit) і тривалість; спосіб агрегації й вікно лишаються типовими.
"""
from dataclasses import replace

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.defaults import DEFAULT_THRESHOLDS
from app.engine.thresholds import Threshold
from app.errors import NotFound, Unprocessable
from app.models import Target, ThresholdRow, User
from app.schemas.thresholds import ThresholdIn, ThresholdOut

# shortcut: кеш у пам'яті процесу (рівно один процес, ТЗ розд. 3): очищається при зміні порогів; при кількох процесах – читати з БД
# Чому кеш: поріг потрібен на кожну точку кожної метрики (тисячі разів на хвилину), а змінюється рідко.
# Структура: {id користувача: {(id об'єкта або None, метрика): Threshold}}.
_cache: dict[int, dict[tuple[int | None, str], Threshold]] = {}


def invalidate(owner_id: int) -> None:
    """Скидає кеш порогів користувача (викликається після будь-якої зміни порогів)."""
    _cache.pop(owner_id, None)


def _merge(default: Threshold, row: ThresholdRow) -> Threshold:
    """Накладає власні рівні користувача на типовий поріг (агрегація й вікно лишаються типовими)."""
    return replace(default, warn=row.warn_value, crit=row.crit_value, duration_s=row.duration_s)


async def _load(db: AsyncSession, owner_id: int) -> dict[tuple[int | None, str], Threshold]:
    """Власні пороги користувача (з кешу або з БД)."""
    if owner_id not in _cache:
        rows = await db.scalars(select(ThresholdRow).where(ThresholdRow.owner_id == owner_id))
        _cache[owner_id] = {(r.target_id, r.metric): _merge(DEFAULT_THRESHOLDS[r.metric], r) for r in rows if r.metric in DEFAULT_THRESHOLDS}
    return _cache[owner_id]


async def resolve(db: AsyncSession, target: Target, metric: str) -> Threshold | None:
    """Чинний поріг метрики для об'єкта або None, якщо для метрики порогів немає (тоді інцидентів за нею не буде)."""
    default = DEFAULT_THRESHOLDS.get(metric)
    if default is None:
        return None
    custom = await _load(db, target.owner_id)
    # `a or b or c`: перший наявний за пріоритетом – об'єкт, потім шаблон, потім типовий.
    return custom.get((target.id, metric)) or custom.get((None, metric)) or default


async def _scope_target(db: AsyncSession, user: User, target_id: int | None) -> None:
    """Перевіряє, що об'єкт належить користувачеві (ізоляція даних); для шаблону (None) перевірка не потрібна."""
    if target_id is not None and await db.scalar(select(Target.id).where(Target.id == target_id, Target.owner_id == user.id)) is None:
        raise NotFound("Об'єкт не знайдено")


async def list_effective(db: AsyncSession, user: User, target_id: int | None) -> list[ThresholdOut]:
    """Чинні пороги для об'єкта (або шаблонні, якщо target_id не задано) з поміткою, звідки вони взялися."""
    await _scope_target(db, user, target_id)
    custom = await _load(db, user.id)
    out = []
    for metric, default in DEFAULT_THRESHOLDS.items():
        th, source = default, "default"
        if (None, metric) in custom:
            th, source = custom[(None, metric)], "template"
        if target_id is not None and (target_id, metric) in custom:
            th, source = custom[(target_id, metric)], "target"
        out.append(ThresholdOut(metric=metric, agg=th.agg, window_s=th.window_s, warn=th.warn, crit=th.crit, direction=th.direction,
                                duration_s=th.duration_s, source=source, levels_editable=default.direction != "equals"))
    return out


def _validate(data: ThresholdIn) -> Threshold:
    """Перевіряє введені користувачем пороги й повертає готовий Threshold (або кидає 422 з поясненням)."""
    default = DEFAULT_THRESHOLDS.get(data.metric)
    if default is None:
        raise Unprocessable("Для цієї метрики порогів немає", details=[{"field": "metric", "message": "Невідома метрика"}])
    if default.direction == "equals":  # бінарні метрики: лише тривалість
        if data.warn is not None or data.crit is not None:
            raise Unprocessable("Для цієї метрики можна змінити лише тривалість", details=[{"field": "crit", "message": "Рівні не змінюються"}])
        return replace(default, duration_s=data.duration_s)
    if data.warn is None and data.crit is None:
        raise Unprocessable("Вкажіть хоча б один поріг", details=[{"field": "warn", "message": "Потрібен поріг попередження або критичний"}])
    if data.warn is not None and data.crit is not None:
        # Порядок: для «більше за» попередження має бути нижчим за критичний; для «менше за» – навпаки.
        ok = data.warn < data.crit if default.direction == "above" else data.warn > data.crit
        if not ok:
            raise Unprocessable("Поріг попередження має бути " + ("менший за критичний" if default.direction == "above" else "більший за критичний"),
                                details=[{"field": "warn", "message": "Порядок порогів порушено"}])
    return replace(default, warn=data.warn, crit=data.crit, duration_s=data.duration_s)


async def save(db: AsyncSession, user: User, data: ThresholdIn) -> None:
    """Зберігає власний поріг (створює або оновлює запис) і скидає кеш."""
    await _scope_target(db, user, data.target_id)
    th = _validate(data)
    row = await db.scalar(select(ThresholdRow).where(ThresholdRow.owner_id == user.id, ThresholdRow.metric == data.metric,
                                                     ThresholdRow.target_id.is_(None) if data.target_id is None else ThresholdRow.target_id == data.target_id))
    if row is None:
        row = ThresholdRow(owner_id=user.id, target_id=data.target_id, metric=data.metric)
        db.add(row)
    row.warn_value, row.crit_value, row.duration_s = th.warn, th.crit, th.duration_s
    await db.flush()
    invalidate(user.id)


async def reset(db: AsyncSession, user: User, metric: str, target_id: int | None) -> None:
    """Видаляє власний поріг: надалі діє шаблон або типове значення."""
    await _scope_target(db, user, target_id)
    res = await db.execute(delete(ThresholdRow).where(ThresholdRow.owner_id == user.id, ThresholdRow.metric == metric,
                                                      ThresholdRow.target_id.is_(None) if target_id is None else ThresholdRow.target_id == target_id))
    if res.rowcount == 0:
        raise NotFound("Власного порога немає")
    invalidate(user.id)
