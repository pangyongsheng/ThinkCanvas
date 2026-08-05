"""Tests for ``app.agents.coder.CoderAgent``.

Demonstrates that the agent is HTTP-independent and can be exercised with
mocks — no FastAPI, no live LLM, no manim subprocess required.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.coder import CoderAgent


def _llm_json_response(thought: str, code: str) -> MagicMock:
    resp = MagicMock()
    resp.content = json.dumps({"thought": thought, "code": code}, ensure_ascii=False)
    return resp


GOOD_CODE = (
    "from manim import *\n\n"
    "class BubbleSort(Scene):\n"
    "    def construct(self):\n"
    "        pass\n"
)


def _fake_render_result(*, ok: bool, error: str | None = None):
    """Mimics ``RenderResult`` (dataclass-like duck)."""
    m = MagicMock()
    m.error = None if ok else error
    m.video_path = "/tmp/fake.mp4" if ok else None
    return m


@pytest.mark.asyncio
async def test_agent_returns_code_on_first_try():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=_llm_json_response("simple plan", GOOD_CODE)
    )

    async def fake_render(code, scene_name):
        return _fake_render_result(ok=True)

    agent = CoderAgent(
        llm=mock_llm,
        max_steps=3,
        renderer=fake_render,
        validator=lambda c: (True, ""),
        scene_name_extractor=lambda c: "BubbleSort",
    )

    result = await agent.run("冒泡排序")

    assert result.code is not None
    assert "BubbleSort" in result.code
    assert len(result.steps) == 1
    assert result.steps[0].validation == "OK"
    assert result.steps[0].render == "rendered ok"


@pytest.mark.asyncio
async def test_agent_retries_when_render_fails():
    """Render failure on first attempt → LLM asked again → second attempt succeeds."""
    call_count = {"n": 0}

    async def fake_render(code, scene_name):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _fake_render_result(ok=False, error="IndexError: list out of range")
        return _fake_render_result(ok=True)

    fixed_code = GOOD_CODE.replace("pass", "title = Text('ok')")
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        side_effect=[
            _llm_json_response("first try", GOOD_CODE),
            _llm_json_response("fixed off-by-one", fixed_code),
        ]
    )

    agent = CoderAgent(
        llm=mock_llm,
        max_steps=4,
        renderer=fake_render,
        validator=lambda c: (True, ""),
        scene_name_extractor=lambda c: "BubbleSort",
    )

    result = await agent.run("冒泡排序")

    assert result.code is not None
    assert result.code == fixed_code.strip()  # agent strips trailing whitespace
    assert len(result.steps) == 2
    assert "render error" in result.steps[0].render
    assert result.steps[1].render == "rendered ok"


@pytest.mark.asyncio
async def test_agent_returns_none_when_validation_keeps_failing():
    """If both attempts fail validation, agent returns None and stops at max_steps."""
    broken_code = "class BubbleSort(Scene):\n    pass\n"  # missing import

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=_llm_json_response("hmm", broken_code))

    async def fake_render(code, scene_name):
        return _fake_render_result(ok=True)

    agent = CoderAgent(
        llm=mock_llm,
        max_steps=3,
        renderer=fake_render,
        validator=lambda c: (False, "missing required import: from manim import *"),
        scene_name_extractor=lambda c: "BubbleSort",
    )

    result = await agent.run("冒泡排序")

    assert result.code is None
    assert len(result.steps) == 3
    assert all("errors: missing required import" in s.validation for s in result.steps)


@pytest.mark.asyncio
async def test_agent_handles_llm_call_failure():
    """Network / API failure → agent skips the step and continues."""
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("connection reset"))

    async def fake_render(code, scene_name):
        return _fake_render_result(ok=True)

    agent = CoderAgent(
        llm=mock_llm,
        max_steps=2,
        renderer=fake_render,
        validator=lambda c: (True, ""),
        scene_name_extractor=lambda c: "BubbleSort",
    )

    result = await agent.run("prompt")

    assert result.code is None
    assert all(s.render == "LLM call failed" for s in result.steps)
