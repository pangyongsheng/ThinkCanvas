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
async def test_middleware_calls_dao_with_tool_steps():
    """AgentPersistenceMiddleware.wrap_tool_call 应调用 dao_steps.write_steps 落库。"""
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.middleware.persistence import AgentPersistenceMiddleware
    from langchain_core.messages import ToolMessage

    # Mock DAO — 不依赖 DB
    dao_steps = MagicMock()
    dao_steps.write_steps = AsyncMock(return_value=1)
    dao_messages = MagicMock()
    dao_messages.create_assistant_shell = AsyncMock(
        return_value=MagicMock(id="msg_123"),
    )
    dao_messages.finalize_after_agent = AsyncMock()

    middleware = AgentPersistenceMiddleware(
        dao_steps=dao_steps, dao_messages=dao_messages,
    )

    class FakeRuntime:
        context = {"conversation_id": "conv_1"}
    class FakeState:
        def get(self, k, default=None): return default

    await middleware.abefore_agent(FakeState(), FakeRuntime())
    assert middleware._message_id == "msg_123"
    dao_messages.create_assistant_shell.assert_awaited_once_with(conversation_id="conv_1")

    class FakeRequest:
        tool_call = {"id": "call_1", "name": "validate_manim_code", "args": {"code": "x"}}
    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="call_1")
    result = await middleware.awrap_tool_call(FakeRequest(), handler)
    assert isinstance(result, ToolMessage)
    assert len(middleware._steps) == 1
    assert middleware._steps[0]["tool_name"] == "validate_manim_code"
    assert middleware._steps[0]["tool_result"] == "ok"

    # after_agent: 调 write_steps + finalize_after_agent
    class FakeState2:
        def get(self, k, default=None):
            if k == "structured_response":
                class S:
                    code = "from manim import *\nclass A(Scene): pass"
                return S()
            return default
    class FakeRuntime2:
        context = {}
    await middleware.aafter_agent(FakeState2(), FakeRuntime2())

    dao_steps.write_steps.assert_awaited_once()
    call_kwargs = dao_steps.write_steps.await_args.kwargs
    assert call_kwargs["message_id"] == "msg_123"
    assert len(call_kwargs["steps"]) == 1

    dao_messages.finalize_after_agent.assert_awaited_once_with(
        message_id="msg_123",
        code="from manim import *\nclass A(Scene): pass",
        scene_name="A",
        status="ok",
    )


@pytest.mark.asyncio
async def test_middleware_emits_sse_events_via_on_event():
    """runtime.context 传 on_event 时，wrap_tool_call 应发 SSE 事件。"""
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.middleware.persistence import AgentPersistenceMiddleware
    from langchain_core.messages import ToolMessage

    dao_steps = MagicMock()
    dao_steps.write_steps = AsyncMock(return_value=0)
    dao_messages = MagicMock()
    dao_messages.create_assistant_shell = AsyncMock(return_value=MagicMock(id="m1"))
    dao_messages.finalize_after_agent = AsyncMock()

    events = []
    async def emit(event, data):
        events.append((event, data))

    middleware = AgentPersistenceMiddleware(
        dao_steps=dao_steps, dao_messages=dao_messages,
    )

    class FakeRuntime:
        context = {"conversation_id": "c1", "on_event": emit}
    class FakeState:
        def get(self, k, default=None): return default
    await middleware.abefore_agent(FakeState(), FakeRuntime())

    class FakeRequest:
        tool_call = {"id": "c1", "name": "validate_manim_code", "args": {}}
    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="c1")
    await middleware.awrap_tool_call(FakeRequest(), handler)

    kinds = [e[0] for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    tool_call_data = next(d for e, d in events if e == "tool_call")
    assert tool_call_data["tool"] == "validate_manim_code"
    tool_result_data = next(d for e, d in events if e == "tool_result")
    assert tool_result_data["status"] == "ok"


@pytest.mark.asyncio
async def test_middleware_swallows_on_event_errors():
    """on_event 抛错不能影响 middleware 主流程。"""
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.middleware.persistence import AgentPersistenceMiddleware

    dao_steps = MagicMock()
    dao_messages = MagicMock()
    dao_messages.create_assistant_shell = AsyncMock(return_value=MagicMock(id="m1"))

    async def bad_on_event(event, data):
        raise RuntimeError("boom")

    middleware = AgentPersistenceMiddleware(
        dao_steps=dao_steps, dao_messages=dao_messages,
    )

    class FakeRuntime:
        context = {"conversation_id": "c1", "on_event": bad_on_event}
    class FakeState:
        def get(self, k, default=None): return default
    # before_agent 里 on_event 调用应被吞掉
    await middleware.abefore_agent(FakeState(), FakeRuntime())
    assert middleware._message_id == "m1"
