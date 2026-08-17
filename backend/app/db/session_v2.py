"""Async SQLAlchemy engine + session factory（v2：隔离 schema agent_v2）。"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.db.session import _settings

V2_SCHEMA = "beta"

engine_v2 = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
    connect_args={"options": f"-c search_path={V2_SCHEMA},public"},
)

async_session_factory_v2 = async_sessionmaker(
    engine_v2, expire_on_commit=False, class_=AsyncSession
)


class BaseV2(DeclarativeBase):
    """v2 模型基类，所有 v2 表 __table_args__ = {"schema": V2_SCHEMA}。"""


async def get_session_v2() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖，每个请求 yield 一个指向 agent_v2 schema 的 AsyncSession。"""
    async with async_session_factory_v2() as session:
        yield session