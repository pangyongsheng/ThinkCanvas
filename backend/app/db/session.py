"""Async SQLAlchemy engine + session factory."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=False, future=True)

async_session_factory = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession per request."""
    async with async_session_factory() as session:
        yield session
