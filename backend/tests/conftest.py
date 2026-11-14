"""测试夹具。需要 MySQL：在 .env 中配置 TEST_DATABASE_URL，未配置或连不上时跳过数据库测试。"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine
from app.models import Base, User
from scripts.seed import ensure_database, seed


@pytest.fixture
async def db():
    """每个测试使用重建并灌入示例数据的测试库，返回 sessionmaker。"""
    url = get_settings().test_database_url
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL")
    try:
        await ensure_database(url)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"连接测试库失败：{type(e).__name__}")
    engine = make_engine(url, pool_size=20, max_overflow=10)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed(s)
    yield maker
    await engine.dispose()


async def get_user(session: AsyncSession, username: str) -> User:
    return (await session.execute(select(User).where(User.username == username))).unique().scalar_one()
