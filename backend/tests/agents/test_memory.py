"""``memory.build_memory_block`` 单测 —— 现在只读 ``user_memories``。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents import memory


def _mem(id_="m1", category="preference", insight="x", confidence=0.5):
    m = MagicMock()
    m.id = id_
    m.category = category
    m.insight = insight
    m.confidence = confidence
    return m


@pytest.mark.asyncio
async def test_empty_memories_returns_empty_string():
    dao = MagicMock()
    dao.list_active = AsyncMock(return_value=[])
    session = MagicMock()
    session.__class__ = MagicMock  # 任意类都行，DAO 注入已 mock

    # 直接构造一个 stub session
    with patch_dao(session, dao):
        out = await memory.build_memory_block(session, user_id="u1")
    assert out == ""


@pytest.mark.asyncio
async def test_renders_preferences_section():
    memories = [_mem("m1", "preference", "用户偏好简洁输出")]
    dao = MagicMock()
    dao.list_active = AsyncMock(return_value=memories)

    with patch_dao(MagicMock(), dao):
        out = await memory.build_memory_block(MagicMock(), user_id="u1")
    assert "## 用户偏好" in out
    assert "用户偏好简洁输出" in out


@pytest.mark.asyncio
async def test_groups_by_category():
    memories = [
        _mem("m1", "preference", "喜欢 zh"),
        _mem("m2", "avoidance", "动画太长"),
        _mem("m3", "pattern", "习惯 refine 多次"),
        _mem("m4", "style_hint", "喜欢高对比"),
    ]
    dao = MagicMock()
    dao.list_active = AsyncMock(return_value=memories)

    with patch_dao(MagicMock(), dao):
        out = await memory.build_memory_block(MagicMock(), user_id="u1")
    assert "## 用户偏好" in out
    assert "## 应避免的事" in out
    assert "## 用户行为模式" in out
    assert "## 风格提示" in out


@pytest.mark.asyncio
async def test_returns_empty_on_exception():
    """DB 异常时 curator 不挂 — 返回空字符串。"""
    dao = MagicMock()
    dao.list_active = AsyncMock(side_effect=RuntimeError("db down"))

    with patch_dao(MagicMock(), dao):
        out = await memory.build_memory_block(MagicMock(), user_id="u1")
    assert out == ""


# ----- helper -----

from contextlib import contextmanager
from app.agents.dao.user_memories import UserMemoriesDAO


@contextmanager
def patch_dao(session, dao):
    """临时让 ``UserMemoriesDAO(session)`` 返回我们的 mock DAO。"""
    orig_init = UserMemoriesDAO.__init__
    UserMemoriesDAO.__init__ = lambda self, s: None
    UserMemoriesDAO.__init__ = lambda self, s: setattr(self, "session", s)
    orig_list_active = UserMemoriesDAO.list_active
    UserMemoriesDAO.list_active = lambda self, uid, limit=20: dao.list_active(uid, limit=limit)
    try:
        yield
    finally:
        UserMemoriesDAO.list_active = orig_list_active
