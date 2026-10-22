"""Базові правила (ТЗ 8.3), що входять у MVP: 1, 2, 3, 6, 10 та MVP-варіанти 5 і 8 (без ping).

Перша умова кожного правила – симптом об'єкта (`self`), для якого є типовий поріг (ТЗ 7.3, «правило повноти»).
"""


def c(scope, metric, op, value, agg="last", window_s=0, instance=None):
    return {"scope": scope, "metric": metric, "op": op, "value": value, "agg": agg, "window_s": window_s, "instance": instance}


BASE_RULES = [
    {"name": "Перевантаження CPU", "applies_to": ["service"], "priority": 10,
     "conditions": [c("self", "response_ms", ">", 1000, "avg", 300), c("host", "cpu_usage", ">", 90, "avg", 300)],
     "cause": "Перевантаження процесора сервера",
     "recommendation": "Знайдіть процеси з найбільшим споживанням CPU (top або Диспетчер завдань), оптимізуйте їх або масштабуйте сервіс."},
    {"name": "Нестача оперативної пам'яті", "applies_to": ["server"], "priority": 10,
     "conditions": [c("self", "ram_usage", ">", 90, "avg", 300), c("self", "swap_usage", ">", 50)],
     "cause": "Нестача оперативної пам'яті",
     "recommendation": "Перевірте витоки пам'яті, перезапустіть сервіс або збільште обсяг RAM."},
    {"name": "Заповнення диска", "applies_to": ["server"], "priority": 10,
     "conditions": [c("self", "disk_usage", ">", 95, instance="any")],
     "cause": "Заповнення диска",
     "recommendation": "Очистіть журнали й тимчасові файли, налаштуйте ротацію журналів."},
    {"name": "Сервіс зупинено, сервер працює", "applies_to": ["service"], "priority": 10,
     "conditions": [c("self", "available", "==", 0), c("host", "agent_alive", "==", 1)],
     "cause": "Сервіс зупинено, сам сервер працює",
     "recommendation": "Перевірте стан служби (systemctl status або «Служби») і перезапустіть її."},
    {"name": "Помилка в застосунку", "applies_to": ["service"], "priority": 10,
     "conditions": [c("self", "available", "==", 0), c("self", "status_code", ">=", 500),
                    c("host", "cpu_usage", "<", 70, "avg", 300)],
     "cause": "Помилка в застосунку",
     "recommendation": "Перегляньте журнал помилок застосунку за час інциденту."},
    {"name": "Очікування вводу-виводу", "applies_to": ["server"], "priority": 10,
     "conditions": [c("self", "load_per_core", ">", 2, "avg", 300), c("self", "cpu_usage", "<", 70, "avg", 300)],
     "cause": "Очікування вводу-виводу (повільний диск)",
     "recommendation": "Перевірте навантаження на диск (iostat)."},
    {"name": "Агент або сервер недоступні", "applies_to": ["server"], "priority": 5,
     "conditions": [c("self", "agent_alive", "==", 0)],
     "cause": "Сервер вимкнений, недоступний мережею або зупинено агента",
     "recommendation": "Перевірте, чи працює віртуальна машина й мережеве з'єднання, а потім чи запущено агента на сервері."},
]
