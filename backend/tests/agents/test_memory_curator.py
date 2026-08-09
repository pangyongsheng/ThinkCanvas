"""MemoryCurator 单测 —— mock LLM 输出，验证 patch 行为。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.memory_curator import MemoryCurator, MemoryEvent


def _fake_memory(id_="m1", category="preference", insight="x", confidence=0.5):
    m = MagicMock()
    m.id = id_
    m.category = category
    m.insight = insight
    m.confidence = confidence
    m.evidence_count = 1
    return m


# ---------------------------------------------------------------------------
# _parse_actions 测试
# ---------------------------------------------------------------------------

def test_parse_actions_clean_json():
    payload = json.dumps({"actions": [
        {"type": "add", "category": "preference", "insight": "test", "confidence": 0.6},
        {"type": "reinforce", "memory_id": "m1"},
    ]})
    out = MemoryCurator._parse_actions(payload)
    assert len(out) == 2


def test_parse_actions_with_fence():
    payload = "```json\n" + json.dumps({"actions": [
        {"type": "add", "category": "pattern", "insight": "y"},
    ]}) + "\n```"
    out = MemoryCurator._parse_actions(payload)
    assert len(out) == 1


def test_parse_actions_filters_unknown_type():
    payload = json.dumps({"actions": [
        {"type": "add", "category": "preference", "insight": "ok"},
        {"type": "explode", "memory_id": "x"},  # 未知 type
        {"type": "reinforce", "memory_id": "m1"},
        "not a dict",  # 非 dict
    ]})
    out = MemoryCurator._parse_actions(payload)
    assert len(out) == 2  # add + reinforce


def test_parse_actions_invalid_json_returns_empty():
    assert MemoryCurator._parse_actions("not json") == []
    assert MemoryCurator._parse_actions("") == []


def test_parse_actions_missing_actions_field():
    payload = json.dumps({"other": []})
    assert MemoryCurator._parse_actions(payload) == []


# ---------------------------------------------------------------------------
# _format_memories 测试
# ---------------------------------------------------------------------------

def test_format_memories_empty():
    assert MemoryCurator._format_memories([]) == ""


def test_format_memories_includes_id_category_insight():
    memories = [
        _fake_memory("m1", "preference", "偏好简洁输出"),
        _fake_memory("m2", "avoidance", "动画太长用户不喜欢"),
    ]
    out = MemoryCurator._format_memories(memories)
    assert "id=m1" in out
    assert "preference" in out
    assert "偏好简洁输出" in out
    assert "id=m2" in out


# ---------------------------------------------------------------------------
# process 测试 —— mock LLM + 验证 apply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_with_no_memories_adds_first_one():
    """用户没有任何 memories，curator 决定 add。"""
    session = MagicMock()
    dao = MagicMock()
    dao.list_all_active = AsyncMock(return_value=[])
    dao.add = AsyncMock()

    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = json.dumps({"actions": [
        {"type": "add", "category": "preference",
         "insight": "用户偏好简洁输出", "confidence": 0.6, "evidence_count": 1},
    ]})
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch("app.agents.memory_curator.get_llm", return_value=fake_llm):
        curator = MemoryCurator.__new__(MemoryCurator)
        curator.session = session
        curator.dao = dao
        event = MemoryEvent(
            kind="generation",
            summary="用户让 agent 演示快速排序，agent 出图",
            extra={"algorithm": "quicksort"},
        )
        n = await curator.process(event, user_id="u1")

    assert n == 1
    dao.add.assert_awaited_once()
    call = dao.add.await_args.kwargs
    assert call["category"] == "preference"
    assert "简洁" in call["insight"]


@pytest.mark.asyncio
async def test_process_with_llm_failure_silently_returns_zero():
    """LLM 抛异常时 curator 不挂，返回 0。"""
    session = MagicMock()
    dao = MagicMock()
    dao.list_all_active = AsyncMock(return_value=[])

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))

    with patch("app.agents.memory_curator.get_llm", return_value=fake_llm):
        curator = MemoryCurator.__new__(MemoryCurator)
        curator.session = session
        curator.dao = dao
        event = MemoryEvent(kind="feedback", summary="x", extra={})
        n = await curator.process(event, user_id="u1")

    assert n == 0
    dao.add.assert_not_called()


@pytest.mark.asyncio
async def test_process_reinforce_existing_memory():
    """curator 决定 reinforce 已有的 memory。"""
    existing = _fake_memory("m_existing", "avoidance", "动画太长", 0.5)
    session = MagicMock()
    dao = MagicMock()
    dao.list_all_active = AsyncMock(return_value=[existing])
    dao.reinforce = AsyncMock(return_value=existing)

    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = json.dumps({"actions": [
        {"type": "reinforce", "memory_id": "m_existing"},
    ]})
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch("app.agents.memory_curator.get_llm", return_value=fake_llm):
        curator = MemoryCurator.__new__(MemoryCurator)
        curator.session = session
        curator.dao = dao
        event = MemoryEvent(
            kind="feedback", summary="用户说太快了", extra={"verdict": "disliked"},
        )
        n = await curator.process(event, user_id="u1")

    assert n == 1
    dao.reinforce.assert_awaited_once_with("m_existing")


@pytest.mark.asyncio
async def test_process_update_existing_memory():
    """curator 决定 update —— 新 insight 替代旧的。"""
    session = MagicMock()
    dao = MagicMock()
    dao.list_all_active = AsyncMock(return_value=[_fake_memory("m_old")])
    dao.update_insight = AsyncMock(return_value=_fake_memory("m_new", insight="new"))

    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = json.dumps({"actions": [
        {"type": "update", "memory_id": "m_old", "new_insight": "精确的洞察"},
    ]})
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch("app.agents.memory_curator.get_llm", return_value=fake_llm):
        curator = MemoryCurator.__new__(MemoryCurator)
        curator.session = session
        curator.dao = dao
        event = MemoryEvent(kind="feedback", summary="x", extra={})
        n = await curator.process(event, user_id="u1")

    assert n == 1
    dao.update_insight.assert_awaited_once_with(
        memory_id="m_old", new_insight="精确的洞察", new_category=None,
    )


@pytest.mark.asyncio
async def test_process_remove_existing_memory():
    """curator 决定 remove —— 旧洞察不再成立。"""
    session = MagicMock()
    dao = MagicMock()
    dao.list_all_active = AsyncMock(return_value=[_fake_memory("m_dead")])
    dao.remove = AsyncMock(return_value=True)

    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = json.dumps({"actions": [
        {"type": "remove", "memory_id": "m_dead", "reason": "不再成立"},
    ]})
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch("app.agents.memory_curator.get_llm", return_value=fake_llm):
        curator = MemoryCurator.__new__(MemoryCurator)
        curator.session = session
        curator.dao = dao
        event = MemoryEvent(kind="feedback", summary="x", extra={})
        n = await curator.process(event, user_id="u1")

    assert n == 1
    dao.remove.assert_awaited_once_with("m_dead")
