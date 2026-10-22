import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from dotenv import dotenv_values

# Тести ходять у окрему БД vigil_test на тому ж сервері, що й розробка.
_ROOT = Path(__file__).resolve().parents[2]
_base = os.environ.get("DATABASE_URL") or dotenv_values(_ROOT / ".env").get("DATABASE_URL", "")
TEST_URL = _base.rsplit("/", 1)[0] + "/vigil_test"
os.environ["DATABASE_URL"] = TEST_URL
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-0000"
os.environ["REGISTRATION_MODE"] = "open"
os.environ["INGEST_MIN_INTERVAL_S"] = "0"


def _dsn(url: str, db: str) -> str:
    return url.replace("+asyncpg", "").rsplit("/", 1)[0] + "/" + db


@pytest.fixture(scope="session", autouse=True)
async def _database():
    admin = await asyncpg.connect(_dsn(TEST_URL, "postgres"))
    await admin.execute("DROP DATABASE IF EXISTS vigil_test WITH (FORCE)")
    await admin.execute("CREATE DATABASE vigil_test")
    await admin.close()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, cwd=Path(__file__).parents[1])
    yield


@pytest.fixture(autouse=True)
async def _clean(_database):
    from app.db import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, rules, metrics RESTART IDENTITY CASCADE"))
    from app.services import ingest
    ingest._last_ingest.clear()
    yield


@pytest.fixture
async def client():
    import httpx
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def make_user(client, email="a@example.com", password="Passw0rd1", name="Ада Лавлейс") -> dict:
    """Реєструє користувача й повертає заголовок авторизації."""
    r = await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def user_factory(client):
    async def _make(**kw):
        return await make_user(client, **kw)
    return _make
