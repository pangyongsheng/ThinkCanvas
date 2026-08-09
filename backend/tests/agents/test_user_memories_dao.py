"""UserMemoriesDAO 单测 — 用 MagicMock 桩 AsyncSession。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.dao.user_memories import UserMemoriesDAO


def _mem(id_="m1", category="preference", insight="x",
         confidence=0.5, evidence_count=1, status="active"):
    m = MagicMock()
    m.id = id_
    m.category = category
    m.insight = insight
    m.confidence = confidence
    m.evidence_count = evidence_count
    m.status = status
    m.superseded_by_id = None
    m.last_reinforced_at = datetime.now()
    m.created_at = datetime.now()
    return m


@pytest.mark.asyncio
async def test_list_active_filters_status_and_superseded():
    """只返回 status='active' 且 superseded_by_id is None 的行。"""
    fake_scalars = MagicMock()
    active = [_mem("a1"), _mem("a2")]
    fake_scalars.__iter__ = lambda self: iter(active)
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars

    session = MagicMock()
    session.execute = AsyncMock(return_value=fake_result)

    dao = UserMemoriesDAO(session)
    out = await dao.list_active("u1", limit=10)
    assert len(out) == 2
    # 断言 SQL 里有 status='active' 和 superseded_by_id is null
    stmt = session.execute.await_args.args[0]
    sql = str(stmt).lower()
    assert "status" in sql
    assert "superseded_by_id" in sql
    assert "confidence" in sql


@pytest.mark.asyncio
async def test_add_creates_new_row():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserMemoriesDAO(session)
    await dao.add(
        user_id="u1", category="preference",
        insight="用户偏好简洁输出",
        confidence=0.6,
    )
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reinforce_increments_evidence_and_confidence():
    existing = _mem(confidence=0.5, evidence_count=1)
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserMemoriesDAO(session)
    out = await dao.reinforce("m1")
    assert out.evidence_count == 2
    assert out.confidence == pytest.approx(0.55, abs=0.01)


@pytest.mark.asyncio
async def test_reinforce_caps_confidence_at_1():
    existing = _mem(confidence=0.99, evidence_count=10)
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserMemoriesDAO(session)
    out = await dao.reinforce("m1")
    assert out.confidence == 1.0  # not 1.04


@pytest.mark.asyncio
async def test_update_insight_creates_new_row_and_supersedes_old():
    existing = _mem(id_="m1", insight="old", confidence=0.6, evidence_count=3)
    added: list = []

    session = MagicMock()

    def _capture_add(obj):
        # 模拟 SQLAlchemy flush 时给新行赋 id
        if getattr(obj, "id", None) is None:
            obj.id = "m_new"
        added.append(obj)
    session.get = AsyncMock(return_value=existing)
    session.add = MagicMock(side_effect=_capture_add)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserMemoriesDAO(session)
    out = await dao.update_insight(
        memory_id="m1", new_insight="new",
    )
    # 旧行被标 superseded，新行是新 ID
    assert existing.status == "superseded"
    assert existing.superseded_by_id == "m_new"
    assert out.insight == "new"
    # evidence_count 继承
    assert out.evidence_count == 3


@pytest.mark.asyncio
async def test_remove_marks_status_decayed():
    existing = _mem()
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()

    dao = UserMemoriesDAO(session)
    ok = await dao.remove("m1")
    assert ok is True
    assert existing.status == "decayed"


@pytest.mark.asyncio
async def test_remove_returns_false_when_missing():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    dao = UserMemoriesDAO(session)
    ok = await dao.remove("nope")
    assert ok is False
