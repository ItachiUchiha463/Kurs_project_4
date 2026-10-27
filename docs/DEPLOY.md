# Розгортання Vigil (MVP)

Одна віртуальна машина з Docker Compose: `db` (TimescaleDB), `backend`, `frontend` (nginx), `caddy` (HTTPS). Міграції та базові правила виконуються самі під час старту бекенда.

## 1. Віртуальна машина в Azure

| Параметр | Значення |
|---|---|
| Образ | Ubuntu 24.04 LTS |
| Розмір | 2 vCPU / 4 ГБ (B2s або найближчий дозволений підпискою Azure for Students) |
| Диск | 32–64 ГБ |
| Публічна IP | статична, з **DNS-міткою**: `vigil-<щось>.<регіон>.cloudapp.azure.com` (безкоштовно) |
| NSG (вхідні) | `80`, `443` – звідусіль; `22` – **лише з вашої IP**. Решту портів не відкривайте |

Бюджет: у Cost Management задайте бюджет з алертом, а демо-машинам увімкніть auto-shutdown на ніч.

## 2. Перший запуск

```bash
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # потім перепідключіться по SSH
git clone https://github.com/ItachiUchiha463/Kurs_project_4.git vigil && cd vigil
cp .env.example .env && nano .env
```

У `.env` обов'язково змініть (генерація секрету: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`):

| Змінна | Що вписати |
|---|---|
| `POSTGRES_PASSWORD` | випадковий пароль |
| `JWT_SECRET` | випадковий секрет, щонайменше 32 символи |
| `DOMAIN` | ваша адреса, напр. `vigil-demo.westeurope.cloudapp.azure.com` |
| `PUBLIC_URL`, `CORS_ORIGINS` | `https://<DOMAIN>` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | з @BotFather (команда `/newbot`); ім'я без `@` |

`DATABASE_URL` у `.env` для Compose не потрібен: його підставляє `docker-compose.yml`.

```bash
docker compose up -d --build
curl https://<DOMAIN>/api/health        # {"db":"ok","background":"ok",...}
```

Caddy сам отримує сертифікат Let's Encrypt, коли `DOMAIN` вказує на публічну IP цієї машини, а порти 80 і 443 відкриті.

## 3. Оновлення й обслуговування

```bash
git pull && docker compose up -d --build     # оновлення
docker compose logs -f backend               # журнал бекенда (JSON, один рядок на подію)
docker compose exec db pg_dump -U vigil vigil | gzip > ~/vigil-$(date +%F).sql.gz   # резервна копія (додайте в cron)
```

**Моніторинг самого сервісу:** у UptimeRobot (або аналогу) створіть перевірку `https://<DOMAIN>/api/health` раз на 5 хв зі сповіщенням у ваш власний канал. `/api/health` повертає 503, якщо недоступна БД або фонові задачі (планувальник, бот, відправка сповіщень) «заснули».

## 4. Агент на демо-машині

Потрібен Linux із systemd. Майстер «Додати об'єкт» показує готову команду з вашою адресою, токеном і назвою – її достатньо виконати на машині:

```bash
curl -fsSL https://raw.githubusercontent.com/ItachiUchiha463/Kurs_project_4/main/agent/install.sh | sudo bash -s -- --server https://ВАША_АДРЕСА --token vgl_... --host НАЗВА
```

Скрипт ставить Python (на Ubuntu/Debian), створює `/opt/vigil-agent`, пише `agent.toml` і запускає службу `vigil-agent`. Додаткові параметри: `--docker`, `--postgres`, `--interval`, `--no-service`; повторний запуск оновлює агента, `--uninstall` видаляє. Журнал: `journalctl -u vigil-agent -f`.

Скрипт береться з гілки `main` на GitHub, тому репозиторій має бути запушений. Ручне встановлення (Windows або без systemd):


```bash
git clone https://github.com/ItachiUchiha463/Kurs_project_4.git && cd Kurs_project_4/agent
python3 -m venv .venv && .venv/bin/pip install psutil httpx
# збережіть agent.toml із майстра в цій папці
.venv/bin/python agent.py --config agent.toml
```

Щоб агент працював постійно (автозапуск і перезапуск після падіння) – служба systemd `/etc/systemd/system/vigil-agent.service`:

```ini
[Unit]
Description=Vigil monitoring agent
After=network-online.target

[Service]
WorkingDirectory=/home/azureuser/Kurs_project_4/agent
ExecStart=/home/azureuser/Kurs_project_4/agent/.venv/bin/python agent.py --config agent.toml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vigil-agent
```

Агент лише **надсилає** дані, тому вхідні порти на демо-машині відкривати не треба (для проби HTTP-перевірки потрібен лише порт 80 на машині, де працює nginx).

## 5. Приймання MVP (ТЗ розд. 17.1) – перевіряється в Azure, а не локально

1. Реєстрація → «Додати об'єкт» → запуск агента на демо-VM → графіки CPU/RAM оновлюються наживо.
2. На демо-VM `stress-ng --cpu 0 --timeout 300s` → за ~2,5 хв інцидент `critical`; у картці – причина й факти, у Telegram – повідомлення з кнопкою.
3. «✅ Підтвердити» в Telegram → у вебінтерфейсі статус «Підтверджено».
4. Зупинка `stress-ng` → інцидент закривається сам, у Telegram – «🟢 Відновлено» відповіддю на «КРИТИЧНО».
5. Сервіс HTTP (напр. nginx на демо-VM, об'єкт «Вебсервіс» з прив'язкою до сервера) → `sudo systemctl stop nginx` → інцидент «Сервіс недоступний» із причиною «Сервіс зупинено, сам сервер працює».
6. Другий обліковий запис не бачить об'єктів першого (автоматичний тест ізоляції: `pytest tests/test_isolation.py`).

Telegram потребує прив'язки: Профіль → «Підключити Telegram» → «Start» у боті.

## 5. Моніторинг Docker-контейнерів

Агент читає Docker Engine API. Доступ до `docker.sock` – це фактично права root, тому агент **не** отримує сокет напряму: поруч запускається `docker-socket-proxy`, який пропускає лише читання списку контейнерів, їхнього стану й статистики:

```bash
docker run -d --name vigil-docker-proxy --restart unless-stopped \
  -p 127.0.0.1:2375:2375 -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e CONTAINERS=1 -e EVENTS=1 -e INFO=1 -e POST=0 tecnativa/docker-socket-proxy
```

Порт опублікований лише на `127.0.0.1`, назовні він не відкривається. У `agent.toml` додайте `docker = true` (адреса за замовчуванням `tcp://127.0.0.1:2375`) і перезапустіть агента. Контейнери з'являться як дочірні об'єкти сервера. Щоб виключити контейнер, додайте йому мітку `vigil.ignore=true` або маску імені в `docker_ignore`.

Docker Desktop на Windows віддає API через іменований канал (`npipe`), який агент не підтримує: у налаштуваннях Docker Desktop ввімкніть «Expose daemon on tcp://localhost:2375 without TLS» (лише для особистого ПК) і вкажіть `docker_url = "tcp://localhost:2375"`.

## 6. Моніторинг PostgreSQL

Базу моніторить агент на тій самій машині або в тій самій мережі. Логін і пароль лежать лише в `agent.toml` і на сервер Vigil не передаються. Створіть окремого користувача лише з правом читати статистику:

```sql
CREATE USER vigil_monitor WITH PASSWORD '...';
GRANT pg_monitor TO vigil_monitor;
```

У `agent.toml` додайте блок (і встановіть драйвер: `.venv/bin/pip install "psycopg[binary]"`):

```toml
[[databases]]
name = "orders-db"
type = "postgres"
dsn  = "postgresql://vigil_monitor:***@localhost:5432/orders"
```

База з'явиться дочірнім об'єктом сервера. Запити до неї мають таймаут 5 с; якщо база не відповідає, агент надсилає лише `db_up = 0`.

## 7. CI/CD (GitHub Actions)

- **CI** (`.github/workflows/ci.yml`) запускається на кожен push у `main` і на pull request: тести бекенда (з TimescaleDB), агента, фронтенду (`tsc`, `vitest`, `vite build`) і збірка образів `backend` та `frontend`.
- **Deploy** (`.github/workflows/deploy.yml`) після успішного CI на `main` (або вручну: Actions → Deploy → Run workflow) заходить на сервер по SSH, виконує `git pull --ff-only && docker compose up -d --build` і перевіряє `/api/health`.

### Налаштування (один раз)

1. На своєму комп'ютері створіть окремий ключ лише для деплою:
```bash
ssh-keygen -t ed25519 -f deploy_key -N ""
```
2. Додайте **публічний** ключ (`deploy_key.pub`) у `~/.ssh/authorized_keys` користувача на сервері.
3. Зніміть відбиток сервера (щоб підключення було до того самого сервера):
```bash
ssh-keyscan -H <адреса-сервера>
```
4. GitHub → репозиторій → Settings → Secrets and variables → Actions:

| Тип | Ім'я | Значення |
|---|---|---|
| Secret | `DEPLOY_HOST` | адреса або IP сервера |
| Secret | `DEPLOY_USER` | користувач SSH (`azureuser`, `ubuntu`) |
| Secret | `DEPLOY_KEY` | вміст файлу `deploy_key` (приватний ключ) |
| Secret | `DEPLOY_KNOWN_HOSTS` | вивід `ssh-keyscan` з кроку 3 |
| Variable | `DEPLOY_URL` | `https://<ваш-домен>` |
| Variable | `DEPLOY_DIR` | папка з проєктом на сервері (типово `vigil`) |

5. Settings → Environments → створіть `production` (за потреби додайте обов'язкового рецензента: деплой чекатиме вашого підтвердження).
6. Settings → Branches → правило для `main`: merge лише після зеленого CI.

Файли `deploy_key` не комітьте (`*.key`/`*.pem` в `.gitignore`, але ім'я `deploy_key` перейменуйте або видаліть після додавання в секрети).

**Обмеження.** Порт 22 має бути досяжний з інтернету: серверам GitHub Actions немає фіксованих IP. Якщо SSH обмежений вашою IP (як на Azure за цією інструкцією), деплой запускайте вручну з комп'ютера, або поставте self-hosted runner на самому сервері.
