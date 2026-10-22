async def test_register_login_me(client):
    r = await client.post("/api/auth/register", json={"email": "A@Example.com", "password": "Passw0rd1", "full_name": "Ада"})
    assert r.status_code == 201
    r = await client.post("/api/auth/login", json={"email": "a@example.com", "password": "Passw0rd1"})
    assert r.status_code == 200
    me = await client.get("/api/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["email"] == "a@example.com"
    assert "password_hash" not in me.json()


async def test_duplicate_email_gives_generic_error(client):
    body = {"email": "a@example.com", "password": "Passw0rd1", "full_name": "Ада"}
    await client.post("/api/auth/register", json=body)
    r = await client.post("/api/auth/register", json=body)
    assert r.status_code == 409
    assert "уже" not in r.json()["error"]["message"]


async def test_weak_password_rejected_with_field(client):
    r = await client.post("/api/auth/register", json={"email": "a@example.com", "password": "short", "full_name": "Ада"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "password"


async def test_wrong_password_and_unknown_email_look_identical(client):
    await client.post("/api/auth/register", json={"email": "a@example.com", "password": "Passw0rd1", "full_name": "Ада"})
    bad_pw = await client.post("/api/auth/login", json={"email": "a@example.com", "password": "Wrong0000"})
    no_user = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong0000"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


async def test_me_requires_token(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": "Bearer garbage"})).status_code == 401


async def test_token_version_revokes_session(client):
    from app.db import SessionLocal
    from sqlalchemy import text
    r = await client.post("/api/auth/register", json={"email": "a@example.com", "password": "Passw0rd1", "full_name": "Ада"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/me", headers=h)).status_code == 200
    async with SessionLocal() as s:
        await s.execute(text("UPDATE users SET token_version = token_version + 1"))
        await s.commit()
    assert (await client.get("/api/me", headers=h)).status_code == 401


async def test_blocked_user_cannot_login(client):
    from app.db import SessionLocal
    from sqlalchemy import text
    await client.post("/api/auth/register", json={"email": "a@example.com", "password": "Passw0rd1", "full_name": "Ада"})
    async with SessionLocal() as s:
        await s.execute(text("UPDATE users SET status = 'blocked'"))
        await s.commit()
    r = await client.post("/api/auth/login", json={"email": "a@example.com", "password": "Passw0rd1"})
    assert r.status_code == 403
