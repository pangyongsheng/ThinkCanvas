"""Shared pytest fixtures.

Provides an in-memory SQLite session + schema so storage tests don't
need the real Postgres. Sync-only because async tests would require
``aiosqlite`` which is not available in this environment.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
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
