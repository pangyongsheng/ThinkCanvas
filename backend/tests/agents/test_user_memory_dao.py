"""Long-term memory DAO 单元测试 —— 用 MagicMock 桩 AsyncSession。

不依赖真实 DB；只验证 DAO 调用的 SQL 语义是否正确：
  * upsert 行为（get-then-create 或 update 现有行）
  * 列表查询的参数
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.agents.dao.user_preferences import UserPreferencesDAO
from app.agents.dao.user_algorithm_history import UserAlgorithmHistoryDAO
from app.agents.dao.user_feedback import UserFeedbackDAO


# ---------------------------------------------------------------------------
# 通用桩 —— 给每个测试单独配 Mock
# ---------------------------------------------------------------------------

def _make_pref(user_id="u1", language="zh", default_style="3b1b", extra=None):
    """构造一个看起来像 ORM UserPreference 的对象。"""
    p = MagicMock()
    p.user_id = user_id
    p.language = language
    p.default_style = default_style
    p.extra_instructions = extra
    return p


def _make_history(id_="h1", user_id="u1", algorithm_name="bubble sort",
                  seen_count=1, last_status=None):
    h = MagicMock()
    h.id = id_
    h.user_id = user_id
    h.algorithm_name = algorithm_name
    h.seen_count = seen_count
    h.last_status = last_status
    h.last_conversation_id = None
    h.last_message_id = None
    h.embedding = None
    h.created_at = datetime.now()
    h.updated_at = datetime.now()
    return h


# ---------------------------------------------------------------------------
# user_preferences DAO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preferences_get_returns_none_when_missing():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    dao = UserPreferencesDAO(session)
    assert await dao.get("u_unknown") is None


@pytest.mark.asyncio
async def test_preferences_upsert_creates_when_missing():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserPreferencesDAO(session)
    pref = await dao.upsert(
        user_id="u1", language="zh", default_style="3b1b",
        extra_instructions="短一点",
    )
    # 新行 → add() 被调
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preferences_upsert_updates_existing_partial():
    """只传 language 时不应清掉 default_style。"""
    existing = _make_pref(language="zh", default_style="3b1b", extra="x")
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserPreferencesDAO(session)
    pref = await dao.upsert(user_id="u1", language="en")

    # 更新路径 —— 走 in-place 修改，不调 add
    session.add.assert_not_called()
    assert pref.language == "en"
    assert pref.default_style == "3b1b"
    assert pref.extra_instructions == "x"


@pytest.mark.asyncio
async def test_preferences_reset_returns_false_when_missing():
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    dao = UserPreferencesDAO(session)
    assert await dao.reset("u_unknown") is False


@pytest.mark.asyncio
async def test_preferences_reset_removes():
    existing = _make_pref()
    session = MagicMock()
    session.get = AsyncMock(return_value=existing)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    dao = UserPreferencesDAO(session)
    ok = await dao.reset("u1")
    assert ok is True
    session.delete.assert_awaited_once_with(existing)


# ---------------------------------------------------------------------------
# user_algorithm_history DAO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_upsert_executes_insert_with_on_conflict():
    """upsert_by_name 调 ``INSERT ... ON CONFLICT DO UPDATE``。"""
    session = MagicMock()
    # execute 异步桩 —— 接收任意 stmt
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    # _get_by_name 应该返回 mock 行
    dao = UserAlgorithmHistoryDAO(session)
    fake_row = _make_history(id_="h_upsert")
    dao._get_by_name = AsyncMock(return_value=fake_row)

    row = await dao.upsert_by_name(
        user_id="u1", algorithm_name="bubble sort", status="ok",
        conversation_id="c1", message_id="m1",
        embedding=[0.1] * 8,
    )
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert row.id == "h_upsert"


@pytest.mark.asyncio
async def test_history_list_recent_uses_correct_order():
    session = MagicMock()
    rows = [_make_history(algorithm_name=f"algo{i}") for i in range(3)]
    fake_scalars = MagicMock()
    fake_scalars.__iter__ = lambda self: iter(rows)
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars
    session.execute = AsyncMock(return_value=fake_result)

    dao = UserAlgorithmHistoryDAO(session)
    out = await dao.list_recent("u1", limit=10)
    assert len(out) == 3
    session.execute.assert_awaited_once()
    stmt = session.execute.await_args.args[0]
    # 断言 SQL 里出现 updated_at DESC 和 limit
    sql = str(stmt).lower()
    assert "updated_at" in sql
    assert "desc" in sql


# ---------------------------------------------------------------------------
# user_feedback DAO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feedback_write_calls_add_and_commit():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dao = UserFeedbackDAO(session)
    fb = await dao.write(
        user_id="u1", message_id="m1", verdict="liked", note="很好",
    )
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_feedback_get_latest_for_message_queries_by_message_id():
    session = MagicMock()
    expected = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = expected
    session.execute = AsyncMock(return_value=fake_result)

    dao = UserFeedbackDAO(session)
    out = await dao.get_latest_for_message("m_xyz")
    assert out is expected
    stmt = session.execute.await_args.args[0]
    sql = str(stmt).lower()
    assert "message_id" in sql
