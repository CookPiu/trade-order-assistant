"""压测与评估脚本共用：在独立数据库上启动一个临时后端实例，结束后停止进程并删除该库。

数据库连接信息取 .env 的 DATABASE_URL，只替换库名；业务库不受影响。
"""
import asyncio
import os
import socket
import statistics
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.models import Base
from scripts.seed import ensure_database, seed

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Demo@2026"


def bench_url(database: str) -> URL:
    return make_url(get_settings().database_url).set(database=database)


async def reset_database(url: URL) -> None:
    """删库重建并灌入示例数据，得到与 README 初始化后相同的状态。"""
    await drop_database(url)
    await ensure_database(url.render_as_string(hide_password=False))
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await seed(session)
    await engine.dispose()


async def drop_database(url: URL) -> None:
    engine = create_async_engine(url.set(database=""))
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
    await engine.dispose()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def instance(database: str, *, keep_db: bool = False):
    """yield (base_url, db_url)：独立库上的后端实例，单进程 uvicorn，与本地开发时的启动方式一致。"""
    url = bench_url(database)
    await reset_database(url)
    port = free_port()
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as c:
            for _ in range(100):
                try:
                    if (await c.get(f"{base}/api/health", timeout=1)).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if proc.poll() is not None:
                    raise RuntimeError(f"后端实例启动失败：{proc.stderr.read().decode(errors='replace')[-2000:]}")
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("后端实例 20 秒内没有就绪")
        yield base, url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not keep_db:
            await drop_database(url)


async def login(client: httpx.AsyncClient, base: str, username: str) -> dict[str, str]:
    r = await client.post(f"{base}/api/auth/login", json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def pct(values: list[float], p: float) -> float:
    """最近秩百分位，values 为空时返回 0。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return s[k]


def summary_ms(values: list[float]) -> dict[str, float]:
    """秒转毫秒的延迟摘要。"""
    ms = [v * 1000 for v in values]
    return {
        "n": len(ms),
        "p50": round(statistics.median(ms), 1) if ms else 0.0,
        "p95": round(pct(ms, 95), 1),
        "max": round(max(ms), 1) if ms else 0.0,
    }


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.perf_counter() - self.t0
