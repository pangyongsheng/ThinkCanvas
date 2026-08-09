"""ConversationsDAO 单元测试 — delete 路径回归覆盖。

用 fake AsyncSession 验证：
  1. 没找到会话 → False
  2. 用户不匹配 → False
  3. 正常路径走 selectinload + bulk DELETE，不再走 ORM session.delete()
  4. 没视频文件的会话也能正常删除
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.agents.dao.conversations import ConversationsDAO


def _conv(id_="01ABC", user_id="01U", messages=None):
    """构造带 messages 的假 Conversation（selectinload 已预填）。"""
    return SimpleNamespace(
        id=id_,
        user_id=user_id,
        title="hello",
        messages=messages or [],
    )


def _msg(id_="m1", role="assistant", video_url=None):
    return SimpleNamespace(id=id_, role=role, video_url=video_url, content="x")


class _FakeSession:
    """假 AsyncSession — 记录 execute / delete / commit 调用。"""

    def __init__(self, conv_to_return):
        self._conv = conv_to_return
        self.commits = 0
        self.executed_stmts: list = []

    async def execute(self, stmt):
        self.executed_stmts.append(stmt)
        # 第一次 execute 是 SELECT Conversation，返回预置的 conv
        # 后面 bulk DELETE 返回 rowcount
        result = MagicMock()
        if self._conv is not None and not self.executed_stmts[:-1]:
            result.scalar_one_or_none.return_value = self._conv
            return result
        result.rowcount = 5
        return result

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_delete_returns_false_when_conv_not_found():
    session = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=fake_result)

    dao = ConversationsDAO(session)
    ok = await dao.delete("01NOPE", user_id="01U")
    assert ok is False
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_returns_false_when_user_mismatch():
    conv = _conv(user_id="01OTHER")
    session = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = conv
    session.execute = AsyncMock(return_value=fake_result)

    dao = ConversationsDAO(session)
    ok = await dao.delete("01ABC", user_id="01U")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_bulk_deletes_messages_then_conversation(tmp_path):
    """正常路径：snapshot 视频 URL，bulk DELETE messages → bulk DELETE conversation。"""
    conv = _conv(
        id_="01CONV",
        user_id="01U",
        messages=[
            _msg("m1", "user"),
            _msg("m2", "assistant", video_url="http://localhost:8000/media/v1.mp4"),
            _msg("m3", "assistant"),  # 无视频
            _msg("m4", "user"),
        ],
    )
    session = _FakeSession(conv)

    dao = ConversationsDAO(session)
    ok = await dao.delete("01CONV", user_id="01U")

    assert ok is True
    # 第一次 execute：SELECT Conversation with selectinload
    # 第二次 + 第三次：bulk DELETE messages / bulk DELETE conversation
    assert len(session.executed_stmts) == 3
    assert session.commits == 1


@pytest.mark.asyncio
async def test_delete_handles_no_messages():
    """没有 messages 的会话也能正常删。"""
    conv = _conv(id_="01EMPTY", user_id="01U", messages=[])
    session = _FakeSession(conv)

    dao = ConversationsDAO(session)
    ok = await dao.delete("01EMPTY", user_id="01U")

    assert ok is True
    assert session.commits == 1


@pytest.mark.asyncio
async def test_delete_handles_no_videos():
    """assistant 消息存在但没 video_url，不报错。"""
    conv = _conv(
        id_="01NOVID",
        user_id="01U",
        messages=[_msg("m1", "user"), _msg("m2", "assistant")],  # 没 video_url
    )
    session = _FakeSession(conv)

    dao = ConversationsDAO(session)
    ok = await dao.delete("01NOVID", user_id="01U")

    assert ok is True
