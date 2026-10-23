FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && useradd --system --uid 1000 --no-create-home app && chown -R app /app
USER app
# рівно один процес: фонові задачі працюють у тому ж event loop (ТЗ розд. 3).
# --proxy-headers: справжня IP клієнта береться з X-Forwarded-For від Caddy (для обмеження частоти входу);
# порт 8000 опублікований лише на 127.0.0.1 хоста, тож стороннього відправника заголовка бути не може.
CMD ["sh", "-c", "alembic upgrade head && python seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
