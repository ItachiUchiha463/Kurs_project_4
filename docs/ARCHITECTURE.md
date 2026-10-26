# Vigil – архітектура і сутності

План складено за підходом ECC: агент `architect` (поточний стан → вимоги → проєкт → компроміси → ADR), skills `fastapi-patterns`, `postgres-patterns`, `api-design`, `architecture-decision-records`.

Джерело вимог – `1_курсак/ТЗ.md`, але зі **зниженою планкою**, прийнятою для записки:

| Було в ТЗ | Тепер |
|---|---|
| Робочі простори, ролі owner/admin/viewer, запрошення | Немає. Кожен користувач бачить лише свої об’єкти |
| Адміністратор платформи | Немає. Базові правила – з `seed.py` |
| Дві мови (uk/en) | Лише українська |
| PDF-звіти | Лише CSV (і перегляд на екрані) |
| Перевірки з боку агента (`location = agent`, `allow_checks`) | Немає. HTTP/TCP/ping – лише з сервера |
| Без змін | Prometheus `/metrics`, 4 СУБД (PostgreSQL, MySQL, Redis, MongoDB), Docker, Telegram, TimescaleDB 30 днів |

> ТЗ синхронізовано з цим документом 22.10.2026: прибране з базового обсягу перелічено в ТЗ, розд. 1, як «Розширення».

---

## 1. Вимоги, що визначають архітектуру

**Функціональні:** прийом метрик від агента; активні перевірки сайтів; пороги → інциденти з гістерезисом і придушенням залежних; логічне виведення причини; Telegram-сповіщення; дашборд у реальному часі; звіт CSV.

**Нефункціональні:**

| Вимога | Ціль |
|---|---|
| Навантаження | до 200 об’єктів, ≈ 2000 рядів метрик, запис кожні 15 с (≈ 130 записів/с) |
| Затримка «збій → сповіщення» | ≤ 30 с + `duration_s` порогу |
| Затримка «метрика → екран» | ≤ 2 с після прийому |
| Зберігання | сирі метрики 30 днів, агрегати 5 хв для графіків 7/30 днів |
| Ізоляція даних | користувач ніколи не бачить чужих об’єктів (404, не 403) |
| Розгортання | одна VM Azure for Students, Docker Compose |

---

## 2. Компоненти

```
                    POST /api/ingest (Bearer: токен агента, кожні 15 с)
 ┌────────────────┐ ──────────────────────────────────┐
 │ Агент (Python) │                                    ▼
 │ psutil, docker,│                 ┌────────────────────────────────────────┐
 │ psycopg, ...   │                 │ Backend: FastAPI, 1 процес (uvicorn)   │
 └────────────────┘                 │                                        │
                                    │  api/ ──► services/ ──► repositories/ ─┼──► PostgreSQL
 ┌────────────────┐  HTTP/TCP/ping  │              │                         │    + TimescaleDB
 │ Сайти, API     │ ◄───────────────┤  checks/scheduler (asyncio)            │
 └────────────────┘                 │  engine/thresholds → engine/inference  │
                                    │  notify/telegram (бот, long polling) ──┼──► Telegram Bot API
                                    │  realtime/hub (WebSocket, кімнати)     │
                                    └───────────────────┬────────────────────┘
                                                        │ REST + WS
                                    ┌───────────────────▼────────────────────┐
                                    │ Frontend: React + TS, Vite, shadcn/ui  │
                                    │ TanStack Query, Recharts               │
                                    └────────────────────────────────────────┘
        Caddy (HTTPS, *.cloudapp.azure.com) перед frontend і backend
```

| Компонент | Відповідальність | Чого НЕ робить |
|---|---|---|
| **Агент** | Збирає метрики системи, Docker, 4 СУБД, `/metrics`; буферизує при обриві зв’язку; шле пакетом | Не оцінює пороги, не виконує перевірок за командою сервера |
| **api/** (роутери) | HTTP-контракт, валідація Pydantic, автентифікація | Без бізнес-логіки і SQL |
| **services/** | Сценарії: створити об’єкт, прийняти пакет, підтвердити інцидент; межі транзакцій | Без знання про HTTP |
| **repositories/** | SQL-запити; **кожен метод приймає `owner_id`** | Без бізнес-правил |
| **engine/** | Чисті функції: оцінка порогу, гістерезис, виведення причини | Без БД і мережі → легко тестувати |
| **checks/** | Планувальник HTTP/TCP/ping, SSRF-захист | – |
| **notify/** | Telegram: відправка, прив’язка чату, скидання пароля | – |
| **realtime/** | WebSocket-хаб, кімнати за `user_id` | Не зберігає стан – після підключення клієнт бере стан через REST |

---

## 3. Шари бекенда і структура коду

За `fastapi-patterns`: тонкі роутери, логіка в сервісах, сесія БД і поточний користувач – через залежності.

```
backend/app/
├─ main.py            # create_app(), lifespan: запуск фонових задач під advisory lock
├─ config.py          # pydantic-settings: DATABASE_URL, JWT_SECRET, TG_TOKEN, RETENTION_DAYS
├─ db.py              # async engine (asyncpg), get_db()
├─ deps.py            # DbDep, CurrentUser (JWT + token_version)
├─ cli.py             # reset-password, block, stats – обслуговування замість адмін-панелі
├─ errors.py          # AppError + глобальні exception_handler → єдиний формат помилки
├─ logging.py         # JSON-лог у stdout, middleware: request_id, метод, шлях, статус, час
├─ models/            # SQLAlchemy 2: user, target, metric, threshold, incident, rule, notification, audit
├─ schemas/           # Pydantic v2: окремо Create / Update / Read
├─ repositories/      # target_repo, metric_repo, incident_repo, rule_repo ...
├─ services/          # auth, targets, ingest, incidents, rules, reports
├─ engine/            # thresholds.py, inference.py, dependencies.py (придушення)
├─ checks/            # scheduler.py, http.py, tcp.py, ping.py, prometheus.py, ssrf.py
├─ notify/            # telegram.py, messages.py
├─ realtime/          # hub.py (кімнати), ws.py (роутер)
├─ api/               # auth, profile, targets, metrics, thresholds, incidents, rules, reports, ingest, health
└─ promparse.py       # спільний з агентом розбір текстового формату Prometheus
```

**Ізоляція даних без просторів.** Єдине правило: репозиторій не має методу без `owner_id`. `get_target(owner_id, target_id)` повертає `None` для чужого об’єкта → роутер віддає 404. Окремий тест перевіряє, що користувач B отримує 404 на кожен ресурс користувача A.

**Мапінг моделей.** Модель SQLAlchemy ніколи не віддається з API напряму. Роутер оголошує `response_model=TargetRead`, а Pydantic будує DTO з атрибутів моделі (`model_config = ConfigDict(from_attributes=True)`), тож поля на кшталт `agent_token_hash` чи `secret_enc` фізично не потрапляють у відповідь. Вхідні DTO (`TargetCreate`, `TargetUpdate`) сервіс перетворює на модель явно – поле за полем.

**Помилки й логування** (ТЗ 3.3). Сервіси кидають `AppError`-нащадків (`NotFound`, `QuotaExceeded`, `Conflict`, `AuthError`); глобальні обробники перетворюють їх на `{"error": …}` з потрібним статусом. Непередбачений виняток → 500 з `request_id`, стек – лише в лог. Кожен запит логується одним JSON-рядком; паролі, токени й тіла запитів не логуються.

**Фонові задачі** (усі в одному event loop, кожна бере `pg_try_advisory_lock`, щоб другий процес їх не дублював):

| Задача | Період | Що робить |
|---|---|---|
| `scheduler` | 1 с тік, кожна перевірка – за своїм `interval_s` | HTTP/TCP/ping → той самий конвеєр, що й ingest |
| `liveness` | 15 с | Агент мовчить 3 інтервали → `agent_alive = 0` |
| `telegram_bot` | long polling | `/start <код>` прив’язує чат, кнопки «Підтвердити» |
| `heartbeat` | 30 с | Оновлює час для `/api/health` |

Очищення старих метрик і стиснення робить TimescaleDB сам (політики в міграції).

---

## 4. Конвеєр обробки метрики

```
ingest / scheduler
  → validate (діапазони, ts не з майбутнього > 5 хв, ліміт рядів на об’єкт)
  → metric_repo.insert_many()                         # один INSERT на пакет
  → targets.last_seen = now()
  → engine.thresholds.evaluate(points)               # стан порушень у пам’яті
       ├─ порушення < duration_s → лише оновити «з якого часу»
       ├─ порушення ≥ duration_s → incident_repo.open()  ─┐
       ├─ рівень змінився        → escalate / deescalate ─┤
       └─ норма з гістерезисом   → resolve()              ─┤
                                                           ▼
  engine.dependencies: батьківський сервер недоступний? → status = suppressed
  engine.inference.diagnose(incident) → diagnoses        # лише при open/escalate
  notify.telegram.send()   (не для suppressed і не після acknowledged)
  realtime.hub.publish(owner_id, events)
```

**Стан «порушення триває з …»** зберігається в пам’яті процесу (словник за ключем `(target_id, metric, instance)`).
`shortcut:` після перезапуску бекенда відлік `duration_s` починається заново – для курсового прийнятно; якщо колись буде кілька процесів, винести в таблицю `breach_state`.

---

## 5. Сутності

### 5.1 ER-діаграма

```
users 1───* targets 1───* metrics            (гіпертаблиця)
  │            │ └─0..1 host (self-reference: контейнер/БД/сервіс → сервер)
  │            ├───* prom_series
  │            ├───* thresholds  (target_id NULL = шаблон користувача)
  │            └───* incidents 1───* incident_events
  │                     │ ├──1 diagnosis ──* (evidence jsonb)
  │                     │ └───* notifications
  │                     └─0..1 suppressed_by (self-reference)
  ├───* rules (owner_id NULL = базове правило)
  ├───* rule_overrides ───1 rules
  └───* audit_log
```

**10 основних сутностей:** User, Target, Metric, PromSeries, Threshold, Incident, IncidentEvent, Rule, Diagnosis, Notification (+ допоміжні `rule_overrides`, `audit_log`, агрегат `metrics_5m`).

### 5.2 Таблиці

Типи – за `postgres-patterns`: ключі `bigint generated always as identity`, рядки `text`, час `timestamptz`, переліки – `text` + `CHECK` (простіше мігрувати, ніж `ENUM`).

**users**

| Поле | Тип | Примітка |
|---|---|---|
| id | bigint PK | |
| email | text, unique | зберігається в нижньому регістрі; лише логін, не підтверджується |
| full_name | text | |
| password_hash | text | bcrypt |
| status | text CHECK (`active`,`blocked`) | блокує власник сервісу через `cli.py` |
| must_change_password | boolean | після тимчасового пароля з `cli.py` |
| token_version | int, default 0 | +1 при зміні пароля / «вийти всюди» → старі JWT стають недійсними |
| telegram_chat_id | bigint, null | особистий чат сповіщень |
| tg_link_code_hash, tg_link_expires | text, timestamptz | одноразовий код прив’язки (10 хв) |
| reset_token_hash, reset_expires | text, timestamptz | скидання пароля через Telegram |
| notify_min_severity | text, default `warning` | `warning` / `critical` |
| muted_until | timestamptz, null | `/mute` у боті або перемикач у профілі |
| created_at | timestamptz | |

**targets** – сервер, сайт/сервіс, контейнер або БД

| Поле | Тип | Примітка |
|---|---|---|
| id | bigint PK | |
| owner_id | bigint FK users, ON DELETE CASCADE | індекс |
| name | text | |
| type | text CHECK (`server`,`service`,`container`,`database`) | |
| check_type | text CHECK (`agent`,`http`,`tcp`,`ping`,`prometheus`,`docker`,`postgres`,`mysql`,`redis`,`mongo`) | |
| source | text CHECK (`manual`,`discovered`) | контейнери й БД агент знаходить сам |
| host_id | bigint FK targets ON DELETE SET NULL, null | видалення сервера не знищує сервіси; на якому сервері працює; основа правил `[host]`, `[siblings]` |
| external_id | text, null | ID контейнера / ключ БД з агента |
| address | text, null | для http (URL), tcp (host:port), ping і сервера з `ping_enabled` (ім'я хоста або IP) |
| expected_status | text, default `200-399` | для http |
| interval_s | int, default 60, CHECK ≥ 15 | |
| agent_token_hash | text, null, unique | лише для `type = server`; токен показується один раз |
| agent_version | text, null | |
| clock_offset_s | real, null | зсув годинника агента |
| status | text CHECK (`ok`,`warning`,`critical`,`unavailable`,`unknown`) | денормалізовано для швидкого дашборда |
| last_seen | timestamptz, null | |
| hidden, enabled | boolean | |
| created_at | timestamptz | |

Індекси: `(owner_id)`; `UNIQUE (host_id, external_id) WHERE external_id IS NOT NULL` – агент не дублює виявлені контейнери.

**metrics** – гіпертаблиця TimescaleDB

| Поле | Тип | Примітка |
|---|---|---|
| target_id | bigint FK targets ON DELETE CASCADE | |
| name | text | `cpu_usage`, `db_connections_pct` ... |
| instance | text, default `''` | розділ диска, ім’я БД, мітки Prometheus |
| value | double precision | |
| ts | timestamptz | |

Без власного `id` (зайвий індекс на 50+ млн рядків). Індекс `(target_id, name, instance, ts DESC)`. Політики: блоки по 1 добі, стиснення після 1 доби, видалення після 30 днів; безперервний агрегат `metrics_5m` (avg/max/min).

**prom_series** – які ряди з `/metrics` імпортувати: `id, target_id FK, metric text, labels jsonb, kind CHECK (gauge, counter, histogram), enabled`. Unique `(target_id, metric, labels)`.

**thresholds**

| Поле | Тип | Примітка |
|---|---|---|
| id | bigint PK | |
| owner_id | bigint FK users | |
| target_id | bigint FK targets, null | NULL = шаблон користувача для всіх його об’єктів |
| metric | text | |
| instance | text, null | NULL = усі ряди |
| agg | text CHECK (`last`,`avg`,`max`,`delta`) | |
| window_s | int, null | |
| warn_value, crit_value | double precision, null | хоча б одне задане |
| direction | text CHECK (`above`,`below`,`equals`) | |
| duration_s | int, default 60 | |
| enabled | boolean | |

`UNIQUE NULLS NOT DISTINCT (owner_id, target_id, metric, instance)` (PostgreSQL 15+). Пошук порогу: об’єкт → шаблон користувача → системні типові (константи в коді, ТЗ 7.3).

**incidents**

| Поле | Тип | Примітка |
|---|---|---|
| id | bigint PK | номер `INC-142` = id |
| owner_id | bigint FK users | денормалізовано: фільтр без JOIN |
| target_id | bigint FK targets | |
| metric, instance | text | |
| severity | text CHECK (`warning`,`critical`) | |
| status | text CHECK (`open`,`acknowledged`,`resolved`,`suppressed`) | |
| suppressed_by | bigint FK incidents, null | інцидент батьківського сервера |
| value_at_open | double precision | |
| first_breach_at, started_at, acknowledged_at, resolved_at | timestamptz | |
| resolve_comment | text, null | обов’язковий при ручному закритті |

Ключовий інваріант – не більше одного незакритого інциденту на ряд:
`CREATE UNIQUE INDEX one_open_incident ON incidents (target_id, metric, instance) WHERE status <> 'resolved';`
Інші індекси: `(owner_id, status, started_at DESC)` для списку; `(suppressed_by)`.

**incident_events** – історія: `id, incident_id FK, type CHECK (opened, escalated, deescalated, acknowledged, resolved, suppressed, notified), value, ts, user_id null, note`. Хронологія на картці інциденту будується саме звідси.

**rules**

| Поле | Тип | Примітка |
|---|---|---|
| id | bigint PK | |
| owner_id | bigint FK users, null | NULL = базове правило (seed, 23 правила з ТЗ 8.3) |
| name, cause, recommendation | text | лише українською |
| applies_to | text[] | `{server}`, `{server,service}` ... |
| conditions | jsonb | масив умов ТЗ 8.1, валідується Pydantic-схемою на вході |
| priority | int | |
| enabled | boolean | |

**rule_overrides** – `owner_id, rule_id, enabled`, PK `(owner_id, rule_id)`: користувач вимикає в себе базове правило, але не змінює його.

**diagnoses** – `id, incident_id FK unique, rule_id FK null` (NULL = «причину не визначено»), `matched_ratio real, evidence jsonb, alternatives jsonb, created_at`. `evidence` – фактичні значення кожної умови, щоб висновок можна було пояснити.

**notifications** – журнал доставки: `id, incident_id FK, chat_id bigint, kind CHECK (opened, escalated, resolved), status CHECK (sent, failed), message_id, error, sent_at`. `message_id` – щоб «Вирішено» приходило відповіддю на початкове повідомлення.

**audit_log** – `id, ts, user_id null, action, entity, entity_id, details jsonb`: входи, зміни порогів і правил, відкинуті пакети метрик.

### 5.3 Машина станів інциденту

```
            порушення ≥ duration_s
   (немає) ───────────────────────► open ◄──── deescalate / escalate (змінює severity)
                                     │  │
            батьківський сервер      │  │ користувач «Підтвердити»
            недоступний              │  ▼
   (немає) ──────────► suppressed    │ acknowledged
                          │          │  │
     сервер повернувся    │          ▼  ▼
                          └──────► resolved  (норма з гістерезисом ≥ duration_s, або вручну з коментарем)
```

---

## 6. API

За `api-design`: ресурси – іменники в множині, префікс `/api`, `201 + Location` для створення, `422` з помилками полів, `404` для чужих ресурсів.

| Метод | Шлях | Призначення |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | email + пароль → JWT (8 год) |
| POST | `/auth/forgot`, `/auth/reset` | скидання пароля через прив’язаний Telegram |
| POST | `/auth/logout-all` | `token_version + 1` |
| GET / PATCH / DELETE | `/me` | профіль, мінімальний рівень сповіщень, видалення облікового запису |
| POST / DELETE | `/me/telegram` | код прив’язки / відв’язати |
| POST | `/me/telegram/test` | тестове повідомлення |
| GET / POST | `/targets` | список зі станом і останніми значеннями / створити |
| GET / PATCH / DELETE | `/targets/{id}` | |
| POST | `/targets/{id}/agent-token` | новий токен агента (показується один раз) |
| GET | `/targets/{id}/children` | контейнери й БД сервера |
| PATCH | `/targets/{id}/hidden` | сховати / показати виявлений контейнер |
| GET | `/targets/{id}/metrics?name=&instance=&from=&to=` | ряд для графіка; > 24 год → з `metrics_5m` |
| POST | `/prometheus/preview` | прочитати `/metrics` і повернути список рядів |
| PUT | `/targets/{id}/prom-series` | вибрані ряди |
| GET / PUT | `/thresholds` | пороги (шаблон + об’єктів) |
| GET | `/incidents?status=&target_id=&severity=&cursor=` | курсорна пагінація за `(started_at, id)` |
| GET | `/incidents/{id}` | картка: події + діагноз |
| POST | `/incidents/{id}/acknowledge` | |
| POST | `/incidents/{id}/resolve` | `{comment}` обов’язковий |
| GET / POST | `/rules` | базові + власні |
| PATCH / DELETE | `/rules/{id}` | лише власні |
| PUT | `/rules/{id}/enabled` | увімкнути / вимкнути базове в себе |
| POST | `/rules/{id}/test?target_id=` | прогнати правило на поточних даних |
| GET | `/reports?from=&to=&format=json\|csv` | |
| GET | `/audit?from=&to=&action=` | журнал подій користувача |
| POST | `/ingest` | токен агента; пакет метрик і виявлених об’єктів |
| GET | `/health` | БД + вік heartbeat фонових задач; 200 / 503 |
| WS | `/ws` | перше повідомлення `{"type":"auth","token":...}`; кімната = `user_id` |

Формат помилки один для всього API:

```json
{"error": {"code": "validation_error", "message": "Некоректні дані",
           "details": [{"field": "interval_s", "message": "Не менше 15 с"}]}}
```

---

## 7. Frontend

```
frontend/src/
├─ main.tsx    # QueryClientProvider, ThemeProvider, RouterProvider
├─ router.tsx  # таблиця маршрутів (ТЗ 11.1), RequireAuth, lazy-сторінки
├─ layouts/    # AppLayout (меню + верхня панель + <Outlet/>), AuthLayout
├─ pages/      # Login, Register, Dashboard, Target, Incidents, Incident, Reports, Settings, AddServer
├─ components/ # shadcn/ui + власні: StatusBadge, MetricChart, IncidentTimeline, ConfirmDialog
├─ forms/      # схеми zod (login, register, target, threshold, rule) – ті самі правила, що ТЗ 6
├─ api/        # client.ts: fetch + Authorization + розбір {"error": …}; типи з OpenAPI
├─ ws/         # одне WS-з’єднання; події оновлюють кеш TanStack Query (setQueryData)
└─ lib/        # auth.ts (токен у localStorage), форматування чисел і часу, plural
```

```
App ─ RouterProvider
      ├─ AuthLayout ─ Login / Register / Forgot / Reset
      └─ RequireAuth ─ AppLayout ─┬─ Sidebar (NavLink + лічильник інцидентів)
                                  ├─ Topbar (пошук, «наживо», тема)
                                  └─ <Outlet/> ─ Dashboard / Target / Incidents / Incident / ...
```

**Стан.** Дані з сервера живуть лише в TanStack Query (кеш, повторні запити, інвалідація після мутацій, оновлення з WS). Глобальний стан інтерфейсу (тема, згорнуте меню) – у React Context. Окремий Redux / Zustand не потрібен.

**Форми.** react-hook-form + `zodResolver`; помилка – під полем, `422` з бекенда розкладається по тих самих полях через `setError`.

**Сесія.** JWT у `localStorage`; `api/client.ts` додає `Authorization`, а на `401` чистить токен і веде на `/login`. Захист від XSS – суворий CSP і заборона `dangerouslySetInnerHTML` (ТЗ 11.1). Прототип `vigil-prototype.html` – еталон екранів і поведінки.

---

## 8. Рішення (ADR)

| № | Рішення | Альтернативи | Чому так |
|---|---|---|---|
| 001 | Модульний моноліт, **один процес**, фонові задачі в asyncio під advisory lock | Celery + Redis, окремі воркери | 200 об’єктів не потребують черги; менше контейнерів і точок відмови |
| 002 | **TimescaleDB** для метрик | Секціонування PostgreSQL вручну; InfluxDB / Prometheus як сховище | Той самий PostgreSQL і SQL; retention і стиснення – політиками без власного коду |
| 003 | Агент **надсилає** (push) | Сервер опитує агентів (pull) | Сервери користувачів за NAT/firewall; вхідні порти відкривати не треба |
| 004 | Правила – **дані в jsonb**, рушій – чисті функції | Правила в коді; готовий рушій (Drools, Experta) | Користувач створює правила з UI; рушій тестується без БД |
| 005 | **WebSocket** для оновлень, REST для стану | Опитування кожні N с; SSE | Мінімальна затримка; кімнати за `user_id`; при обриві – повторне підключення 1→30 с |
| 006 | Ізоляція через `owner_id` у кожному методі репозиторію, чужий → 404 | Row Level Security PostgreSQL | Просто й явно; RLS – запасний варіант, якщо з’являться простори |
| 007 | Шари router → service → repository, **не** гексагональна архітектура | Hexagonal (порти/адаптери) | Одна БД і один транспорт – порти не окупляться за місяць розробки |
| 008 | JWT у `localStorage` + суворий CSP | httpOnly-cookie + CSRF-токен | Простіше для SPA і WebSocket-автентифікації; ризик XSS закриває CSP, вкрадений токен анулюється `token_version` |
| 009 | Форми: react-hook-form + zod | Formik + Yup; власна валідація | Стандартна зв’язка shadcn/ui, менше повторних рендерів, схеми типізовані TypeScript |

---

## 9. Ризики

| Ризик | Захід |
|---|---|
| Користувач задає адресу перевірки у внутрішню мережу сервера (SSRF) | IP перевіряється на кожному запиті, лише `is_global`; без автоматичних редиректів |
| Два процеси бекенда дублюють перевірки й Telegram-бота | `pg_try_advisory_lock` на кожну фонову задачу |
| Агент шле сміття або забагато рядів | Pydantic-валідація, ліміт рядів на об’єкт, відкинуті пакети → `audit_log` |
| Шторм сповіщень при падінні сервера | Придушення дочірніх інцидентів (`suppressed_by`), одне повідомлення «і ще N залежних» |
| Перезапуск бекенда скидає відлік `duration_s` | Прийнято для MVP (див. розд. 4) |

---

## 10. Порядок збирання MVP

**Що** входить у MVP і наступні ітерації – лише ТЗ, розд. 17 (обсяг, критерії готовності, календар). Тут – тільки **в якому порядку** збирати шари, щоб кожен крок спирався на готовий попередній:

1. Скелет: `create_app`, конфіг, БД, Alembic, Docker Compose (`db`, `backend`).
2. `users` + реєстрація / вхід (JWT) + репозиторії з `owner_id` + тест ізоляції.
3. `targets` + токен агента + `/ingest` + гіпертаблиця `metrics`; агент лише з `system.py`.
4. `checks/` (HTTP + `ssrf.py`) і `agent_alive` – той самий конвеєр, що й `/ingest`.
5. `engine/thresholds` + `incidents` + `incident_events` (unit-тести на гістерезис і `duration_s`).
6. `engine/inference` + `diagnoses` + seed правил, що входять у MVP за ТЗ 17.1.
7. Telegram: прив’язка + сповіщення + кнопка «Підтвердити».
8. Frontend: вхід, дашборд, сторінка об’єкта з графіком, список і картка інциденту, майстер додавання сервера; WebSocket.
9. Розгортання в Azure і перевірка критеріїв готовності MVP (ТЗ 17.1).
