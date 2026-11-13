"""Оцінювач порогів (ТЗ розд. 7.1): чисті функції без БД і мережі.

step() отримує вже агреговане значення й стан ряду, а повертає новий стан і дії для сервісу.

Як читати цей файл (від простого до складного):
  1. Threshold – опис порога однієї метрики (що вважати проблемою і як довго терпіти).
  2. State – пам'ять про ряд між викликами (коли почалося порушення, чи відкритий інцидент).
  3. Action (Open, Escalate, Deescalate, Resolve) – що має зробити сервіс за результатом кроку.
  4. step() – сама логіка: «стан + нове значення + час -> новий стан + дії».

Чому функція чиста: час `ts` передається параметром, а не береться з годинника. Тому в тестах
можна «перемотувати» час і перевіряти будь-який сценарій за мілісекунди (див. tests/test_thresholds.py).
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

# Рівні серйозності інциденту.
Severity = Literal["warning", "critical"]
# Напрямок порушення:
#   above  – погано, коли значення БІЛЬШЕ за поріг (CPU, RAM, час відповіді);
#   below  – погано, коли МЕНШЕ (влучання в кеш БД: чим нижче, тим гірше);
#   equals – бінарна метрика (доступність 0/1): порушення, коли значення дорівнює порогу.
Direction = Literal["above", "below", "equals"]

# SQL-вирази агрегатів за вікно часу. Вони підставляються в запити в services/pipeline.py і services/diagnosis.py.
# Назви ключів збігаються з полем `agg` у порогах і правилах виведення.
AGG_SQL = {"avg": "avg(value)", "max": "max(value)", "min": "min(value)", "delta": "(max(value) - min(value))",
           "slope": "regr_slope(value, extract(epoch FROM ts)) * 3600"}  # slope – зміна за годину за вікно (лінійна регресія); потрібні щонайменше 2 точки

# Запас на закриття інциденту: значення має відійти від порога ще на 5 %, інакше показник,
# що «гуляє» біля межі, відкривав би й закривав інцидент щохвилини (ТЗ 7.1).
HYSTERESIS = 0.05


@dataclass(frozen=True)
class Threshold:
    """Поріг однієї метрики. frozen=True: після створення не змінюється, тож безпечно кешується й ділиться між запитами."""
    metric: str
    # Як з «сирих» точок отримати одне число для порівняння:
    #   last – остання точка; avg/max – за вікно window_s секунд; delta – приріст лічильника за вікно (max - min).
    agg: Literal["last", "avg", "max", "delta"] = "last"
    window_s: int = 0          # довжина вікна для avg/max/delta, секунд (для last не потрібна)
    warn: float | None = None  # поріг «попередження»; None – такого рівня немає (бінарні метрики мають лише crit)
    crit: float | None = None  # поріг «критичний»
    direction: Direction = "above"
    duration_s: int = 60       # скільки секунд порушення має тривати, щоб відкрити інцидент (і скільки спокою – щоб закрити)


@dataclass(frozen=True)
class State:
    """Пам'ять про один ряд (метрика + об'єкт) між викликами step(). Нова версія створюється на кожному кроці."""
    breach_since: datetime | None = None   # з якого моменту триває порушення (ще без інциденту)
    incident: Severity | None = None       # рівень відкритого інциденту; None – інциденту немає
    calm_since: datetime | None = None     # з якого моменту значення в нормі (з гістерезисом), для закриття


# Нижче – «дії»: що step() просить зробити сервіс. Сам step() нічого не пише в БД, лише повертає ці об'єкти.
@dataclass(frozen=True)
class Open:
    """Відкрити інцидент."""
    severity: Severity
    value: float
    first_breach_at: datetime  # коли порушення почалося (раніше, ніж відкрито інцидент: пройшла тривалість)


@dataclass(frozen=True)
class Escalate:
    """Підвищити рівень: warning -> critical."""
    severity: Severity
    value: float


@dataclass(frozen=True)
class Deescalate:
    """Знизити рівень: critical -> warning (значення вийшло з критичної зони, але ще не в нормі)."""
    severity: Severity
    value: float


@dataclass(frozen=True)
class Resolve:
    """Закрити інцидент: значення в нормі достатньо довго."""
    value: float


Action = Open | Escalate | Deescalate | Resolve


def _beyond(value: float, limit: float, direction: Direction) -> bool:
    """Чи порушує значення поріг у заданому напрямку. Порівняння строгі: рівно на межі ще «норма» (ТЗ 7.1)."""
    if direction == "above":
        return value > limit
    if direction == "below":
        return value < limit
    return value == limit


def classify(value: float, th: Threshold) -> Severity | None:
    """Рівень порушення для значення: critical має перевагу над warning; None – усе гаразд.

    Критичний поріг перевіряється першим: якщо значення за обома порогами, воно критичне, а не «попередження».
    """
    if th.crit is not None and _beyond(value, th.crit, th.direction):
        return "critical"
    if th.warn is not None and _beyond(value, th.warn, th.direction):
        return "warning"
    return None


def _clear(value: float, limit: float, th: Threshold) -> bool:
    """Значення повернулося за поріг із запасом (гістерезис); бінарні метрики запасу не мають."""
    if th.direction == "equals":
        return value != limit
    if th.direction == "above":
        # поріг 0 («є хоч одна») запасу не має: 5 % від нуля – це нуль, і інцидент ніколи б не закрився
        return value < limit * (1 - HYSTERESIS) if limit > 0 else value <= limit
    # «нижче за»: запас – один пункт (відсотки): 5 % від 95 дали б 99,75, і здорова БД із 97 % лишалася б у інциденті
    return value >= limit + 1


def _lowest(th: Threshold) -> float:
    """Найнижчий заданий поріг (warn, а якщо його немає – crit): від нього рахується гістерезис."""
    return th.warn if th.warn is not None else th.crit


def step(state: State, th: Threshold, value: float, ts: datetime) -> tuple[State, list[Action]]:
    """Один крок автомата: (стан, нове значення, час) -> (новий стан, дії).

    Станів три, і між ними переходять так:

        [норма] --порушення тримається duration_s--> [інцидент warning] --значення за crit--> [інцидент critical]
           ^                                                |   ^                                  |
           |                                                |   +----вийшло з crit, але не в нормі--+
           +--- значення в нормі duration_s (із запасом) ---+  (Deescalate)
                               (Resolve)

    Параметри: state – попередній стан цього ряду; th – поріг; value – нове (вже агреговане) значення; ts – його час.
    """
    level = classify(value, th)
    dur = timedelta(seconds=th.duration_s)

    # --- Гілка 1: інциденту немає ---
    if state.incident is None:
        if level is None:
            # Усе гаразд: скидаємо лічильник порушення, нічого не робимо.
            return State(), []
        # Порушення є. Запам'ятовуємо, коли воно почалося (перша точка за порогом).
        since = state.breach_since or ts
        if ts - since >= dur:
            # Порушення тримається вже достатньо довго -> відкриваємо інцидент.
            # Короткі сплески (менші за duration_s) сюди не доходять: у цьому й сенс тривалості.
            return State(breach_since=since, incident=level), [Open(level, value, since)]
        # Ще не досить довго: чекаємо наступних точок.
        return State(breach_since=since), []

    # --- Гілка 2: інцидент уже відкритий ---
    if level == "critical" and state.incident == "warning":
        # Стало гірше: підвищуємо рівень.
        return replace(state, incident="critical", calm_since=None), [Escalate("critical", value)]
    if level is not None:
        # Порушення триває. Якщо інцидент був critical, а тепер лише warning і значення вже
        # з запасом вийшло з критичної зони -> знижуємо рівень (деескалація).
        if level == "warning" and state.incident == "critical" and th.crit is not None \
                and _clear(value, th.crit, th) and th.direction != "equals":
            return replace(state, incident="warning", calm_since=None), [Deescalate("warning", value)]
        # Інакше нічого не змінюємо, лише скидаємо відлік «спокою».
        return replace(state, calm_since=None), []

    # --- Гілка 3: інцидент відкритий, а значення вже не порушує поріг ---
    # Закриваємо не одразу: спершу значення має відійти від порога із запасом (гістерезис),
    # а потім пробути там duration_s секунд.
    if not _clear(value, _lowest(th), th):
        # Ще в «сірій зоні» біля межі: відлік спокою не веде.
        return replace(state, calm_since=None), []
    calm = state.calm_since or ts
    if ts - calm >= dur:
        return State(), [Resolve(value)]
    return replace(state, calm_since=calm), []
