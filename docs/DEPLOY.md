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

Потрібні Python 3.11+ і git. Токен і `agent.toml` показує майстер «Додати об'єкт» (потрібно, щоб `host` у файлі збігався з назвою об'єкта).

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
