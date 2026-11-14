"""接口测试公用的登录客户端。"""
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import app


@asynccontextmanager
async def api_client(db, username: str):
    async def override():
        async with db() as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": username, "password": "Demo@2026"})
            client.headers["Authorization"] = f"Bearer {r.json()['token']}"
            yield client
    finally:
        app.dependency_overrides.clear()
