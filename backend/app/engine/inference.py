"""Механізм логічного виведення (ТЗ розд. 8): продукційні правила «ЯКЩО умови – ТО причина».

Чисті функції: на вході правила й факти (агрегати метрик), на виході висновок із доказами.

Ідея у двох реченнях. «Правило» каже: «якщо CPU сервера понад 90 % і сервіс відповідає повільніше за 1 с,
то причина – перевантаження процесора». Механізм перевіряє всі правила проти фактичних значень метрик і обирає
те, у якого виконано всі умови; якщо таких кілька, перемагає конкретніше.

Де що відбувається:
  services/diagnosis.py збирає ФАКТИ з БД (значення метрик) і викликає diagnose() звідси;
  evaluate() перевіряє одне правило й будує «докази» (які умови виконано і з якими значеннями);
  diagnose() порівнює всі правила й повертає головну причину та можливі альтернативи.

Тут немає звернень до БД чи мережі: тому ядро легко тестується (tests/test_inference.py).
"""
from dataclasses import dataclass, field
from typing import Literal

# Про що умова:
#   self     – сам об'єкт, на якому відкрито інцидент;
#   host     – сервер, на якому цей об'єкт працює (для сервера – він сам);
#   siblings – інші об'єкти того самого сервера (контейнери, бази, сервіси).
Scope = Literal["self", "host", "siblings"]  # siblings – інші об'єкти того самого сервера
# Оператори порівняння як функції: так умову з даних («>», 90) можна обчислити без eval.
OPS = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b, "==": lambda a, b: a == b,
}
PARTIAL_MIN = 0.5  # правила з такою часткою виконаних умов показуються як «можливі причини»

# Людські назви метрик і одиниці для пояснень («CPU сервера, середнє за 5 хв: 96,1 % > 90 %»).
METRIC_LABELS = {
    "cpu_usage": "CPU", "ram_usage": "RAM", "swap_usage": "Swap", "disk_usage": "Диск",
    "load_per_core": "Навантаження на ядро", "response_ms": "Час відповіді", "available": "Доступність",
    "agent_alive": "Агент працює", "status_code": "HTTP-код", "net_total": "Мережа",
    "ping_available": "Ping", "packet_loss": "Втрати пакетів",
    "container_running": "Контейнер працює", "container_oom_killed": "Нестача пам'яті (OOM)", "container_exit_code": "Код виходу",
    "ram_available_mb": "Вільна RAM", "uptime_h": "Час роботи сервера", "cpu_iowait": "CPU чекає диск", "cpu_steal": "CPU забирає хост",
    "inode_usage": "Заповненість inode", "disk_read": "Читання диска", "disk_write": "Запис на диск",
    "container_health": "Healthcheck", "container_restarts": "Перезапуски", "container_cpu": "CPU контейнера", "container_mem": "RAM контейнера",
    "db_up": "База даних доступна", "db_connections_pct": "З'єднання, % від максимуму", "db_idle_in_tx": "Транзакції idle in transaction",
    "db_longest_query_s": "Найдовший запит", "db_locks_waiting": "Запити, що чекають блокування", "db_cache_hit_pct": "Влучання в кеш",
}
UNITS = {"ram_available_mb": "МБ", "uptime_h": "год", "cpu_iowait": "%", "cpu_steal": "%", "inode_usage": "%", "disk_read": "КБ/с", "disk_write": "КБ/с",
         "cpu_usage": "%", "ram_usage": "%", "swap_usage": "%", "disk_usage": "%", "response_ms": "мс", "net_total": "КБ/с", "packet_loss": "%", "container_cpu": "%", "container_mem": "%",
         "db_connections_pct": "%", "db_cache_hit_pct": "%", "db_longest_query_s": "с"}
AGG_TEXT = {"avg": "середнє", "max": "максимум", "min": "мінімум", "delta": "приріст", "slope": "зміна за годину"}


@dataclass(frozen=True)
class Condition:
    """Одна умова правила: «<про що> <метрика> <агрегація за вікно> <оператор> <значення>»."""
    scope: Scope
    metric: str
    op: str
    value: float
    agg: str = "last"   # last / avg / max / min / delta / slope (див. AGG_SQL в engine/thresholds.py)
    window_s: int = 0   # вікно для агрегації, секунд
    instance: str | None = None  # None – ряд без instance; "any" – найгірший серед рядів; "same" – як в інциденті
    sibling_type: str | None = None  # для siblings: тип сусідів (container, database, service)
    match: str = "any"  # для siblings: умова має виконуватися хоча б для одного (any) чи для всіх (all)

    @property
    def fact_key(self) -> tuple:
        """Ключ, за яким факт шукається в словнику фактів. Дві умови з однаковим ключем потребують одного значення,
        тому services/diagnosis.py рахує його з БД лише раз (економить запити)."""
        return (self.scope, self.metric, self.agg, self.window_s, self.instance, self.sibling_type)


@dataclass(frozen=True)
class Rule:
    """Правило: набір умов («І») і висновок. Береться з таблиці rules (базові й власні правила користувача)."""
    id: int | None
    name: str
    cause: str            # ймовірна причина (показується на картці інциденту)
    recommendation: str   # що робити
    applies_to: tuple[str, ...]  # до яких типів об'єктів застосовується (server, service, container, database)
    conditions: tuple[Condition, ...]
    priority: int = 0
    own: bool = False  # власне правило користувача: вище за базове з тією ж кількістю умов


@dataclass(frozen=True)
class Evidence:
    """Один «доказ»: умова правила, чи вона виконана і яке було фактичне значення (напр. «96,1 % > 90 %»)."""
    ok: bool
    text: str
    value: str


@dataclass(frozen=True)
class Match:
    """Результат перевірки одного правила."""
    rule: Rule
    ratio: float  # частка виконаних умов: 1.0 – усі, 0.5 – половина
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnosis:
    """Підсумок: головна причина (або None, якщо жодне правило не виконано повністю) і можливі інші причини."""
    primary: Match | None
    alternatives: list[Match]


def _num(v: float) -> str:
    """Число для людини: 1 знак після коми, без зайвих нулів, кома замість крапки (96.1 -> «96,1», 90.0 -> «90»)."""
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _describe(c: Condition, names: dict[str, str]) -> str:
    """Текст умови для пояснення: «CPU web-01, середнє за 5 хв»."""
    who = names[c.scope] + (f" ({c.sibling_type})" if c.scope == "siblings" else "")
    label = METRIC_LABELS.get(c.metric, c.metric)
    window = f", {AGG_TEXT[c.agg]} за {c.window_s // 60} хв" if c.agg != "last" and c.window_s else ""
    if c.agg == "slope":
        window = f", {AGG_TEXT[c.agg]} (за останні {c.window_s // 60} хв)"
    return f"{label} {who}{window}"


def evaluate(rule: Rule, facts: dict[tuple, float | list[float] | None], names: dict[str, str]) -> Match:
    """Перевіряє одне правило проти фактів і будує докази.

    facts – словник «ключ умови -> значення»: число, список чисел (для siblings: значення кожного сусіда)
    або None, якщо даних немає. Умова без даних вважається невиконаною («немає даних»).
    """
    evidence, ok_count = [], 0
    for c in rule.conditions:
        actual = facts.get(c.fact_key)
        unit = f" {UNITS[c.metric]}" if c.metric in UNITS else ""
        if c.agg == "slope":
            unit += "/год"  # швидкість зміни показуємо як «%/год»
        if actual is None or actual == []:
            evidence.append(Evidence(False, _describe(c, names), "немає даних"))
            continue
        if isinstance(actual, list):  # siblings: значення кожного сусіда
            # Умова про сусідів: перевіряємо кожного й комбінуємо за правилом match:
            # all – має виконуватися для всіх, any – хоча б для одного.
            hits = [OPS[c.op](v, c.value) for v in actual]
            ok = all(hits) if c.match == "all" else any(hits)
            # показуємо найвідповідніше значення: те, що виконує умову, а інакше найближче до неї
            pick = [v for v, h in zip(actual, hits) if h] or actual
            actual = max(pick) if c.op in (">", ">=") else min(pick) if c.op in ("<", "<=") else pick[0]
            ok_count += ok
            evidence.append(Evidence(ok, _describe(c, names), f"{_num(actual)}{unit} {c.op} {_num(c.value)}{unit}"))
            continue
        # Звичайна умова з одним значенням.
        ok = OPS[c.op](actual, c.value)
        ok_count += ok
        evidence.append(Evidence(ok, _describe(c, names), f"{_num(actual)}{unit} {c.op} {_num(c.value)}{unit}"))
    return Match(rule, ok_count / len(rule.conditions) if rule.conditions else 0.0, evidence)


def diagnose(rules: list[Rule], facts: dict[tuple, float | list[float] | None], names: dict[str, str], target_type: str) -> Diagnosis:
    """Правило з усіма виконаними умовами – причина; конкретніше (більше умов) вище, далі власні, далі priority.

    Порядок вибору, коли кілька правил виконано повністю:
      1) більше умов = конкретніше правило (воно каже більше, тож і надійніше);
      2) власне правило користувача перемагає базове з тією ж кількістю умов;
      3) вищий priority.
    Правила, виконані лише частково (від PARTIAL_MIN), стають «можливими причинами» в картці інциденту.
    """
    # Беремо лише правила, придатні для типу цього об'єкта.
    matches = [evaluate(r, facts, names) for r in rules if target_type in r.applies_to]
    full = sorted((m for m in matches if m.ratio == 1.0),
                  key=lambda m: (len(m.rule.conditions), m.rule.own, m.rule.priority), reverse=True)
    primary = full[0] if full else None
    partial = sorted((m for m in matches if PARTIAL_MIN <= m.ratio < 1.0), key=lambda m: m.ratio, reverse=True)
    # Альтернативи: спершу решта повністю виконаних правил, потім часткові (від більшого збігу до меншого).
    return Diagnosis(primary, [m for m in full[1:]] + partial)
