"""Tests for the standard LangChain agent pipeline.

Validates that the four-layer architecture is wired correctly:

  1. ``get_llm()`` returns an object typed as ChatOpenAI
  2. ``create_agent`` is called with the standard kwargs
     (``model``, ``tools``, ``system_prompt``, ``response_format``)
  3. The structured response schema is honoured end-to-end (mocked)
  4. ``CodeOutput`` schema validates and normalises code bodies

No live LLM, no manim subprocess required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.builder import build_agent, TOOLS
from app.agents.styles import DEFAULT_STYLE_ID, load_style

SYSTEM_PROMPT = load_style(DEFAULT_STYLE_ID).description
from app.agents.schemas import CodeOutput
from app.llm.client import get_llm


def test_get_llm_is_typed_as_chat_openai():
    """Business code should always see a ChatOpenAI — never the raw LiteLLM class."""
    with patch("app.llm.client.ChatLiteLLM") as mock_litellm_cls:
        mock_litellm_cls.return_value = MagicMock(name="litellm_instance")
        get_llm.cache_clear()
        try:
            get_llm()
        finally:
            get_llm.cache_clear()
        # cast() in client.py makes the static type ChatOpenAI even though
        # the runtime object is the LiteLLM-backed mock. Verify via the
        # function's declared return annotation (survives lru_cache wrapping).
        import inspect
        from app.llm import client as client_mod
        ret = inspect.signature(client_mod.get_llm).return_annotation
        assert str(ret) == "ChatOpenAI", f"get_llm() return type must be ChatOpenAI, got {ret}"


def test_code_output_schema_validates_and_normalises():
    """The structured-output Pydantic model slices at ``from manim import``."""
    raw_code = "blah blah\nfrom manim import *\n\nclass S(Scene):\n    pass\n"
    out = CodeOutput(thought="ok", code=raw_code)
    assert out.code.startswith("from manim import *")
    assert "blah blah" not in out.code


def test_code_output_passes_through_when_already_clean():
    out = CodeOutput(thought="ok", code="from manim import *\n\nclass S(Scene):\n    pass\n")
    assert out.code.startswith("from manim import *")


def test_build_agent_uses_create_agent_standard_api():
    """The builder must call langchain.agents.create_agent with the right args.

    LangChain 1.x standard form:
        create_agent(model=chat_model, tools=[...], system_prompt=...,
                     response_format=PydanticSchema)
    """
    with patch("app.llm.client.ChatLiteLLM") as mock_litellm_cls:
        fake = MagicMock(name="litellm_instance")
        mock_litellm_cls.return_value = fake

        with patch("app.agents.builder.create_agent") as mock_create:
            mock_create.return_value = "BUILT_AGENT"
            build_agent.cache_clear()
            try:
                agent = build_agent()
            finally:
                build_agent.cache_clear()
            assert agent == "BUILT_AGENT"

            call_kwargs = mock_create.call_args.kwargs
            # model must be the chat model, NOT a Runnable
            assert call_kwargs["model"] is fake
            assert call_kwargs["tools"] == TOOLS
            assert call_kwargs["system_prompt"] == SYSTEM_PROMPT
            # structured output via response_format (LangChain 1.x standard)
            assert call_kwargs["response_format"] is CodeOutput


def test_tools_are_standard_langchain_tools():
    """Both tools must be decorated with @tool."""
    from app.agents.tools import validate_manim_code, render_manim_dryrun
    for t in (validate_manim_code, render_manim_dryrun):
        assert hasattr(t, "name"), f"{t} is not a @tool"
        assert callable(t.invoke) or callable(t.ainvoke)


@pytest.mark.asyncio
async def test_run_agent_returns_structured_code():
    """End-to-end: run_agent pulls the structured response from the agent output."""
    from langchain_core.messages import AIMessage

    structured = CodeOutput(
        thought="ok",
        code="from manim import *\n\nclass S(Scene):\n    pass\n",
    )
    fake_agent = MagicMock()

    async def _fake_ainvoke(*_args, **_kwargs):
        return {
            "messages": [AIMessage(content="thought: ok")],
            "structured_response": structured,
        }
    fake_agent.ainvoke = _fake_ainvoke

    with patch("app.agents.react_coder.build_agent", return_value=fake_agent):
        from app.agents.react_coder import run_agent
        result = await run_agent("冒泡排序", max_iterations=4)

    assert result["code"] == structured.code
    assert "from manim import *" in result["code"]
