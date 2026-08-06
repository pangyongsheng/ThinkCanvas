"""Fallback recovery for LLM providers that emit thinking blocks instead of
strict JSON structured output (notably MiniMax-M3 via LiteLLM).

The agent runs through ``langchain.agents.create_agent`` with
``response_format=CodeOutput``. When the provider returns its thoughts
inline (``AIMessage.content == [{"type": "thinking", ...}, ...]``)
LangChain's structured parser can't locate the CodeOutput JSON and we end
up with ``structured_response is None``. ``run_agent`` must still surface
a runnable code string so the user-facing pipeline can render a video.
"""
from __future__ import annotations

import json as _json
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


@pytest.mark.asyncio
async def test_recover_code_from_thinking_blocks():
    """MiniMax-style list content with thinking + text blocks -> recovered code."""
    thinking_blocks = [
        {"type": "thinking", "thinking": "Step-by-step plan..."},
        {
            "type": "text",
            "text": _json.dumps({"thought": "draw trapezoid", "code": RUNNABLE_CODE}),
        },
    ]
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [
                AIMessage(content="求梯形面积"),
                AIMessage(content=thinking_blocks),
            ],
            "structured_response": None,
        }

    fake_agent.ainvoke = _fake_ainvoke
    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("求梯形面积", style_id="academic", max_iterations=8)

    assert result["code"] is not None
    assert result["code"].startswith("from manim import *")
    assert "TrapezoidArea" in result["code"]


@pytest.mark.asyncio
async def test_recover_code_from_json_fence():
    """LLM wraps JSON in ```json fences - strip and recover."""
    fenced = (
        "Some prose\n"
        "```json\n"
        + _json.dumps({"thought": "ok", "code": RUNNABLE_CODE})
        + "\n```\n"
    )
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {"messages": [AIMessage(content=fenced)], "structured_response": None}

    fake_agent.ainvoke = _fake_ainvoke
    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("merge sort", max_iterations=4)

    assert result["code"] is not None
    assert "from manim import *" in result["code"]


@pytest.mark.asyncio
async def test_recover_json_embedded_in_prose():
    """Prose + JSON object inline - regex sweep should catch it."""
    prose_with_json = (
        "Let me think...\n"
        + _json.dumps({"thought": "embedded", "code": RUNNABLE_CODE})
        + "\n"
    )
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {"messages": [AIMessage(content=prose_with_json)], "structured_response": None}

    fake_agent.ainvoke = _fake_ainvoke
    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("quicksort", max_iterations=4)

    assert result["code"] is not None
    assert "TrapezoidArea" in result["code"]


@pytest.mark.asyncio
async def test_no_valid_json_returns_none_not_crash():
    """Fallback must give up cleanly - return None, not invent code."""
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="Sorry, I cannot help with that.")],
            "structured_response": None,
        }

    fake_agent.ainvoke = _fake_ainvoke
    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("???", max_iterations=4)

    assert result["code"] is None


@pytest.mark.asyncio
async def test_normal_structured_response_still_works():
    """Regression: happy path (structured_response set) must keep working."""
    structured = CodeOutput(thought="ok", code=RUNNABLE_CODE)
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="thought: ok")],
            "structured_response": structured,
        }

    fake_agent.ainvoke = _fake_ainvoke
    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("ok", max_iterations=4)

    assert result["code"].rstrip() == RUNNABLE_CODE.rstrip()
    assert result["code"].startswith("from manim import *")
    assert "TrapezoidArea(Scene)" in result["code"]
