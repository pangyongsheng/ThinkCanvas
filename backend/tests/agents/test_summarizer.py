"""Tests for the few-shot summariser.

We mock both ``get_llm`` and the embedding service so the tests don't
need real API/model downloads — the summariser's job is to produce a
clean sentence + delegate embedding to the service module.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents import summarizer





def _patch_llm(reply: str):
    """Replace ``app.agents.summarizer.get_llm`` with a mock that
    returns an AIMessage with ``reply`` as content.
    """
    fake = MagicMock()

    async def _ainvoke(messages):
        return AIMessage(content=reply)

    fake.ainvoke = _ainvoke
    return patch("app.agents.summarizer.get_llm", return_value=fake)


@pytest.mark.asyncio
async def test_summariser_returns_clean_sentence():
    with _patch_llm("冒泡排序可视化：两两比较数字并交换"):
        out = await summarizer.summarise_few_shot("冒泡排序", "code")
    assert out == "冒泡排序可视化：两两比较数字并交换"


@pytest.mark.asyncio
async def test_summariser_strips_quotes_and_markdown():
    """Models sometimes wrap the answer in quotes / backticks / a heading."""
    with _patch_llm('"**一句话总结**：二叉树 BFS 遍历，从根逐层访问"'):
        out = await summarizer.summarise_few_shot("二叉树 BFS", "code")
    assert out.startswith("一句话总结") or summary.startswith("二叉树")
    # No leftover double-quotes.
    assert '"' not in out


@pytest.mark.asyncio
async def test_summariser_keeps_first_line_when_multi_line():
    with _patch_llm("第一句重要的话\n第二句废话\n第三句"):
        out = await summarizer.summarise_few_shot("x", "code")
    assert out == "第一句重要的话"


@pytest.mark.asyncio
async def test_summariser_falls_back_to_prompt_on_llm_failure():
    """If the LLM call raises, we fall back to the user prompt rather
    than dropping the row — saving still works.
    """
    fake = MagicMock()
    async def _boom(_):
        raise RuntimeError("network down")
    fake.ainvoke = _boom

    with patch("app.agents.summarizer.get_llm", return_value=fake):
        out = await summarizer.summarise_few_shot("用户的原问题", "code")
    assert out == "用户的原问题"


@pytest.mark.asyncio
async def test_summariser_caps_very_long_replies():
    """Defensive cap so a rambling LLM doesn't blow up the prompt slot."""
    long = "a" * 500
    with _patch_llm(long):
        out = await summarizer.summarise_few_shot("x", "code")
    assert len(out) <= 200

# ---------------------------------------------------------------------------
# _extract_text_from_message
# ---------------------------------------------------------------------------


def test_extract_text_from_plain_string():
    assert summarizer._extract_text_from_message("hello") == "hello"


def test_extract_text_from_list_with_text_block():
    """MiniMax returns content as typed blocks — we want the text one."""
    content = [
        {"type": "thinking", "thinking": "let me think..."},
        {"type": "text", "text": "二叉树 BFS 遍历：逐层访问节点"},
    ]
    assert summarizer._extract_text_from_message(content) == "二叉树 BFS 遍历：逐层访问节点"


def test_extract_text_from_list_with_only_thinking_falls_through():
    """If the model emits only thinking (no text), we get empty string
    and the summariser falls back to the user prompt."""
    content = [{"type": "thinking", "thinking": "..."}]
    assert summarizer._extract_text_from_message(content) == ""


def test_extract_text_from_none():
    assert summarizer._extract_text_from_message(None) == ""


def test_extract_text_from_empty_list():
    assert summarizer._extract_text_from_message([]) == ""


# ---------------------------------------------------------------------------
# End-to-end: MiniMax-style list content flows through summarise_few_shot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summariser_handles_list_content():
    """The original bug: model returns list, code crashed, fell back to
    prompt. With the fix, the text block should be extracted and used.
    """
    fake = MagicMock()

    async def _ainvoke(_messages):
        # AIMessage with content as list — exactly what MiniMax does.
        return AIMessage(content=[
            {"type": "thinking", "thinking": "用户问的是快速排序"},
            {"type": "text", "text": "快速排序：选基准元素递归分治两侧"},
        ])

    fake.ainvoke = _ainvoke
    with patch("app.agents.summarizer.get_llm", return_value=fake):
        out = await summarizer.summarise_few_shot("快速排序算法", "code")
    assert out == "快速排序：选基准元素递归分治两侧"
    assert out != "快速排序算法"  # must NOT have hit the fallback path
