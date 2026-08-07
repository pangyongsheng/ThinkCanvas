"""Tests for ``app.agents.refine.run_refine``.

The refine agent rebuilds the LangChain agent each call (system prompt
depends on dynamic prev_code + instruction) and reuses the structured
output extraction pipeline from ``react_coder``. These tests mock the
agent at the seam so we can exercise:

  * prompt assembly (prev_code + instruction wired into the human message)
  * happy path: structured_response.code returned as-is
  * fallback path: thinking-blocks recovered same as in cold-start path
  * empty inputs rejected loudly (not silently passed through)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.schemas import CodeOutput


RUNNABLE_CODE = (
    "from manim import *\n"
    "\n"
    "class TrapezoidArea(Scene):\n"
    "    def construct(self):\n"
    "        pass\n"
)


def _patch_build_agent(fake_agent):
    """Patch the seam where ``run_refine`` fetches its agent.

    We patch ``app.agents.refine.build_agent`` (not the one in builder)
    because refine imported it directly into its own namespace.
    """
    return patch("app.agents.refine.build_agent", return_value=fake_agent)


@pytest.mark.asyncio
async def test_refine_returns_code_when_structured_response_present():
    fake_agent = MagicMock()

    structured = CodeOutput(thought="tweaked bg", code=RUNNABLE_CODE)

    async def _fake_ainvoke(invoke_input, config=None):
        # Capture the input for inspection in assertion below.
        _fake_ainvoke.captured = invoke_input
        return {
            "messages": [AIMessage(content="ok")],
            "structured_response": structured,
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        result = await run_refine(
            prev_code="from manim import *\n\nclass Old(Scene):\n    pass\n",
            instruction="把背景换成白色",
            style_id="academic",
        )

    assert result["code"].rstrip() == RUNNABLE_CODE.rstrip()

    # Verify the human message carried both the previous code and the instruction
    # so the LLM has the context it needs to make a small, targeted change.
    msgs = _fake_ainvoke.captured["messages"]
    assert len(msgs) == 1
    content = msgs[0].content
    assert "把背景换成白色" in content
    assert "[上一版代码]" in content
    assert "from manim import *" in content
    assert result["code"].rstrip() == RUNNABLE_CODE.rstrip()


@pytest.mark.asyncio
async def test_refine_recovers_code_from_thinking_blocks():
    """MiniMax behaviour: structured_response is None because the thinking
    channel leaks into AIMessage.content. Fallback should still recover.
    """
    thinking_blocks = [
        {"type": "thinking", "thinking": "调整颜色..."},
        {"type": "text", "text": json.dumps({"thought": "ok", "code": RUNNABLE_CODE})},
    ]
    fake_agent = MagicMock()

    async def _fake_ainvoke(invoke_input, config=None):
        return {
            "messages": [
                AIMessage(content="adjusting"),
                AIMessage(content=thinking_blocks),
            ],
            "structured_response": None,
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        result = await run_refine(
            prev_code="# old\n",
            instruction="red theme",
            style_id="3b1b",
        )

    assert result["code"].rstrip() == RUNNABLE_CODE.rstrip()


@pytest.mark.asyncio
async def test_refine_includes_user_history_in_prompt():
    """User history should appear in the prompt before the latest code,
    so the LLM understands progressive refinement.
    """
    from langchain_core.messages import HumanMessage

    fake_agent = MagicMock()
    captured: dict = {}

    async def _fake_ainvoke(invoke_input, config=None):
        # Capture the user message so we can assert on its content.
        captured["messages"] = invoke_input["messages"]
        return {
            "messages": [AIMessage(content="done")],
            "structured_response": CodeOutput(thought="ok", code=RUNNABLE_CODE),
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        await run_refine(
            prev_code=RUNNABLE_CODE,
            instruction="and now make the background red",
            style_id="3b1b",
            user_history=[
                "show trapezoid area",
                "highlight the height in blue",
            ],
        )

    assert len(captured["messages"]) == 1
    user_msg = captured["messages"][0]
    assert isinstance(user_msg, HumanMessage)
    body = user_msg.content
    assert "[历史用户指令]" in body
    assert "- show trapezoid area" in body
    assert "- highlight the height in blue" in body
    assert "[上一版代码]" in body
    # Current instruction is highlighted separately, not in the history bullets.
    assert "[本次用户调整要求]" in body
    assert "and now make the background red" in body


@pytest.mark.asyncio
async def test_refine_omits_history_block_when_empty():
    """First refinement in a conversation has no user history yet."""
    from langchain_core.messages import HumanMessage

    fake_agent = MagicMock()
    captured: dict = {}

    async def _fake_ainvoke(invoke_input, config=None):
        captured["messages"] = invoke_input["messages"]
        return {
            "messages": [AIMessage(content="ok")],
            "structured_response": CodeOutput(thought="ok", code=RUNNABLE_CODE),
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        await run_refine(
            prev_code=RUNNABLE_CODE,
            instruction="red background",
            style_id="3b1b",
            user_history=[],
        )

    body = captured["messages"][0].content
    assert "[历史用户指令]" not in body
    assert "[上一版代码]" in body
    assert "[本次用户调整要求]" in body


@pytest.mark.asyncio
async def test_refine_returns_none_when_no_code_anywhere():
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="I cannot help with that.")],
            "structured_response": None,
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        result = await run_refine(prev_code="# old\n", instruction="anything")

    assert result["code"] is None


@pytest.mark.asyncio
async def test_refine_rejects_empty_prev_code():
    from app.agents.refine import run_refine

    with pytest.raises(ValueError, match="prev_code"):
        await run_refine(prev_code="   \n", instruction="x")


@pytest.mark.asyncio
async def test_refine_rejects_empty_instruction():
    from app.agents.refine import run_refine

    with pytest.raises(ValueError, match="instruction"):
        await run_refine(prev_code="# something", instruction="   \n")


@pytest.mark.asyncio
async def test_refine_extracts_python_fence_from_thinking_block():
    """MiniMax under load: the full code lives inside the thinking block's
    markdown code fence, with no JSON wrapper around it. Fallback order:
    recover_code_from_messages → aggressive_scan → python_fence → done.
    """
    fence = (
        "```python\n"
        "from manim import *\n"
        "\n"
        "class ParallelogramArea(Scene):\n"
        "    def construct(self):\n"
        "        p = Polygon([0,0,0],[4,0,0],[6,2,0],[2,2,0], color=BLUE)\n"
        "        self.play(Create(p))\n"
        "```\n"
    )
    thinking_block = {
        "type": "thinking",
        "thinking": (
            "Let me try this version:\n\n" + fence +
            "\n\nHmm wait, that has an issue with the visualization..."
        ),
    }
    text_block = {"type": "text", "text": "\n\n"}  # empty final answer

    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [
                AIMessage(content="refine"),
                AIMessage(content=[thinking_block, text_block]),
            ],
            "structured_response": None,
        }
    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        result = await run_refine(
            prev_code="# old\n",
            instruction="show area formula",
            style_id="3b1b",
        )

    assert result["code"] is not None
    assert result["code"].startswith("from manim import *")
    assert "ParallelogramArea" in result["code"]


@pytest.mark.asyncio
async def test_refine_retries_when_output_looks_truncated():
    """If the first ainvoke has a ``thinking`` block + empty ``text`` block,
    retry once. The retry succeeds. Verify the second response is used.
    """
    thinking_block = {"type": "thinking", "thinking": "...still thinking..."}
    empty_text = {"type": "text", "text": "\n\n"}

    thinking_only = AIMessage(content=[thinking_block, empty_text])
    real_answer = CodeOutput(
        thought="done",
        code="from manim import *\n\nclass RetryWin(Scene):\n    def construct(self):\n        pass\n",
    )
    real_text = AIMessage(content="ok")

    fake_agent = MagicMock()
    call_count = {"n": 0}

    async def _fake_ainvoke(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"messages": [AIMessage(content="refine"), thinking_only], "structured_response": None}
        return {"messages": [AIMessage(content="refine"), real_text], "structured_response": real_answer}

    fake_agent.ainvoke = _fake_ainvoke

    with _patch_build_agent(fake_agent):
        from app.agents.refine import run_refine
        result = await run_refine(prev_code="# old\n", instruction="x", style_id="3b1b")

    assert call_count["n"] == 2, "should have retried exactly once"
    assert result["code"] is not None
    assert "RetryWin" in result["code"]
