"""Tests for the few-shot summariser.

We mock ``get_llm`` so the tests don't need a real API connection —
the summariser's job is to produce a single clean sentence from the
LLM's reply.
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
    assert out.startswith("一句话总结") or out.startswith("二叉树")
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
