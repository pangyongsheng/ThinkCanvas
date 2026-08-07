"""Shared pytest fixtures.

Two flavours of session:
  * ``session``           — sync, default for storage unit tests
  * ``async_session``     — async, for code that uses ``AsyncSession``
                            (retriever, conversations endpoint, etc.)

Both run on in-memory SQLite so no Postgres needed in CI.

Note: the async fixture uses ``aiosqlite`` if available; if not, the
test that asks for it should be skipped. Right now the async code
paths in this project are only exercised in production (no async
unit tests yet) — see ``tests/agents/test_retriever.py`` for an
example that mocks out the async surface.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base


@pytest.fixture
def session() -> Session:
    """Fresh in-memory SQLite + sync Session per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def async_session_marker():
    """Marker fixture — async session tests need aiosqlite in this env.

    Tests that genuinely need an async DB session should mark themselves
    with ``@pytest.mark.skipif(not HAS_AIOSQLITE, ...)`` (see
    ``tests/conftest.py`` import) or use the mock-based pattern in
    ``tests/agents/test_retriever.py``.
    """
    return None
