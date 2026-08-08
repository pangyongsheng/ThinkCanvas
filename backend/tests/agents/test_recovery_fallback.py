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


@pytest.mark.asyncio
async def test_invoke_with_recovery_emits_on_event():
    """invoke_with_recovery should emit thinking + tool events via on_event callback."""
    from app.agents.agent_recovery import invoke_with_recovery
    from langchain_core.messages import AIMessage, ToolMessage

    # mock 一个 agent：返回包含 tool_call + tool_result 的消息
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "call_1", "name": "validate_manim_code", "args": {"code": "x"}},
                    ],
                ),
                ToolMessage(content="ok", tool_call_id="call_1"),
                AIMessage(content="done"),
            ],
            "structured_response": None,
        }

    fake_agent.ainvoke = _fake_ainvoke

    # 抓事件
    events: list[tuple[str, dict]] = []

    async def on_event(event: str, data: dict) -> None:
        events.append((event, data))

    result = await invoke_with_recovery(
        fake_agent,
        {"messages": []},
        max_iterations=4,
        label="test",
        style_id="3b1b",
        on_event=on_event,
    )

    kinds = [e[0] for e in events]
    assert "thinking" in kinds, f"expected thinking event, got {kinds}"
    assert "tool_call" in kinds, f"expected tool_call event, got {kinds}"
    assert "tool_result" in kinds, f"expected tool_result event, got {kinds}"

    # tool_call data 应包含 tool name
    tool_call_data = next(d for e, d in events if e == "tool_call")
    assert tool_call_data["tool"] == "validate_manim_code"

    # tool_result data 应包含 status
    tool_result_data = next(d for e, d in events if e == "tool_result")
    assert tool_result_data["status"] == "ok"
    assert tool_result_data["tool"] == "validate_manim_code"

    # thinking 事件应在 ainvoke 之前发出
    assert kinds[0] == "thinking"


@pytest.mark.asyncio
async def test_invoke_with_recovery_no_callback_unchanged():
    """不传 on_event 时行为应该跟以前一模一样 —— 无 callback。"""
    from app.agents.agent_recovery import invoke_with_recovery
    from langchain_core.messages import AIMessage

    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="hello")],
            "structured_response": None,
        }

    fake_agent.ainvoke = _fake_ainvoke

    # 不传 on_event 也不应该报错
    result = await invoke_with_recovery(
        fake_agent,
        {"messages": []},
        max_iterations=4,
        label="test",
        style_id="3b1b",
    )
    assert result is not None


@pytest.mark.asyncio
async def test_invoke_with_recovery_swallows_callback_errors():
    """callback 抛错不能影响主流程。"""
    from app.agents.agent_recovery import invoke_with_recovery
    from langchain_core.messages import AIMessage

    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="hello")],
            "structured_response": None,
        }

    fake_agent.ainvoke = _fake_ainvoke

    async def bad_on_event(event: str, data: dict) -> None:
        raise RuntimeError("callback intentionally broken")

    # 不应该抛
    result = await invoke_with_recovery(
        fake_agent,
        {"messages": []},
        max_iterations=4,
        label="test",
        style_id="3b1b",
        on_event=bad_on_event,
    )
    assert result is not None
