# Vigil – система моніторингу серверів (курсовий проєкт)

## Джерела правди

- **ТЗ:** `C:\Users\user\source\repos\1_курсак\ТЗ.md` – обсяг, метрики, правила, API, тести, план ітерацій (розд. 17).
- **Архітектура:** `docs/ARCHITECTURE.md` – шари, таблиці, ADR.
- **Інтерфейс:** `docs/prototype/vigil-prototype.html` – еталон екранів, кольорів і поведінки.

Не змінюй ТЗ мовчки. Якщо реалізація розходиться з ТЗ – спершу онови ТЗ і `docs/ARCHITECTURE.md` (і скажи, чи зачеплено записку), потім код.

## Обсяг

Базовий обсяг **знижений** (ТЗ розд. 1): без робочих просторів і ролей, без адмін-панелі, лише українська, звіти – екран і CSV, перевірки HTTP/TCP/ping – лише з сервера. Кожен користувач бачить тільки свої об'єкти. Простори, ролі, англійська, PDF, перевірки з агента – «Бонус», лише якщо лишиться час.

Поточна ітерація – **MVP до 26.10.2026** (ТЗ 17.1; порядок збирання – `docs/ARCHITECTURE.md`, розд. 10).

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, Pydantic v2, httpx; PostgreSQL 16 + TimescaleDB.
- **Frontend:** React + TypeScript + Vite, React Router, TanStack Query, shadcn/ui + Tailwind, react-hook-form + zod, Recharts.
- **Agent:** Python, psutil, httpx.
- **Deploy:** Docker Compose (`db`, `backend`, `frontend`, `caddy`), Azure VM.

## Структура

```
backend/app/   api/ → services/ → repositories/ → models/;  engine/ (чисті функції), checks/, notify/, realtime/
agent/         agent.py, collectors/
frontend/src/  router.tsx, layouts/, pages/, components/, forms/, api/, ws/, lib/
docs/          ARCHITECTURE.md, prototype/
```

## Команди

```bash
docker compose up -d db                    # TimescaleDB на localhost:5433 (.env з .env.example)
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/alembic upgrade head         # міграції
.venv/Scripts/python -m pytest -q          # тести (окрема БД vigil_test створюється сама)
.venv/Scripts/uvicorn app.main:app --reload --workers 1
```

## Жорсткі правила

1. Доступ до даних – лише через репозиторії; **кожен метод приймає `owner_id`**. Чужий об'єкт → 404, не 403.
2. Серверні запити на адреси користувача – лише через `checks/ssrf.py`.
3. Шари не перескакуються: роутер не пише SQL; `engine/` не торкається БД і мережі.
4. Кожна нова функція – з тестом (pytest). Обов'язково: оцінювач порогів, рушій виведення, SSRF, ізоляція користувачів.
5. Uvicorn – лише `--workers 1`; фонові задачі – лише під `pg_try_advisory_lock`.
6. Облікові дані користувачів (крім паролів – bcrypt) – лише зашифровані `SECRETS_KEY`, ніколи у відповідях API. Модель БД не віддається з API напряму – тільки через `response_model`.
7. Час – завжди UTC (`timestamptz`) у БД і API; київський час – лише на фронтенді.
8. Помилки – через `AppError` і глобальні обробники (ТЗ 3.3); логи – JSON, без паролів, токенів і тіл запитів.
9. Секрети – лише в `.env` (у git не потрапляє). Репозиторій **публічний**.

## Стиль

- Тексти інтерфейсу, повідомлення про помилки, сповіщення – українською, без кальок, тире – коротке (–).
- Коментарі в коді – українською, лише «чому», а не «що».
- Коміти – маленькі, одна фіча на коміт; гілка на ітерацію.
