"""``algorithm_extractor`` 单测 —— mock LLM + embedding。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents import algorithm_extractor


def test_parse_algorithm_clean_json():
    assert algorithm_extractor._parse_algorithm('{"algorithm": "bubble sort"}') == "bubble sort"


def test_parse_algorithm_with_fence():
    payload = '```json\n{"algorithm": "binary search"}\n```'
    assert algorithm_extractor._parse_algorithm(payload) == "binary search"


def test_parse_algorithm_empty_falls_back():
    assert algorithm_extractor._parse_algorithm("") == "general"
    assert algorithm_extractor._parse_algorithm("not json at all") == "general"


def test_parse_algorithm_lowercases_and_truncates():
    payload = '{"algorithm": "  BUBBLE SORT  "}'
    out = algorithm_extractor._parse_algorithm(payload)
    assert out == "bubble sort"


@pytest.mark.asyncio
async def test_extract_returns_algorithm_and_embedding():
    """正常路径：LLM 输出 JSON + embedding 调通 → 返回 (name, vec)。"""
    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = '{"algorithm": "merge sort"}'
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch.object(algorithm_extractor, "get_llm", return_value=fake_llm), \
         patch.object(algorithm_extractor, "embed_one", return_value=[0.1] * 8):
        name, vec = await algorithm_extractor.extract_algorithm_name(
            user_prompt="演示归并排序", code="def merge_sort():\n    pass\n",
        )
    assert name == "merge sort"
    assert vec == [0.1] * 8


@pytest.mark.asyncio
async def test_extract_falls_back_when_llm_returns_garbage():
    """LLM 输出非 JSON → 回落到 'general'，embedding 仍尝试生成。"""
    fake_llm = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = "这是个算法"  # 不是 JSON
    fake_llm.ainvoke = AsyncMock(return_value=fake_msg)

    with patch.object(algorithm_extractor, "get_llm", return_value=fake_llm), \
         patch.object(algorithm_extractor, "embed_one", return_value=[0.2] * 4):
        name, vec = await algorithm_extractor.extract_algorithm_name(
            user_prompt="演示", code="x",
        )
    assert name == "general"
    assert vec == [0.2] * 4


@pytest.mark.asyncio
async def test_extract_returns_general_when_llm_throws():
    """LLM 抛异常时也不挂，返回 ('general', None)。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))
    with patch.object(algorithm_extractor, "get_llm", return_value=fake_llm), \
         patch.object(algorithm_extractor, "embed_one", side_effect=RuntimeError("embed down")):
        name, vec = await algorithm_extractor.extract_algorithm_name(
            user_prompt="x", code="y",
        )
    assert name == "general"
    assert vec is None
