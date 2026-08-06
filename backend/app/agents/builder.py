"""Agent factory — the only place that calls ``langchain.agents.create_agent``.

This module is the canonical seam between:
  * the LLM (delivered by ``app.llm.client.get_llm`` — typed as ChatOpenAI)
  * the tools (``app.agents.tools`` — plain ``@tool``-decorated functions)
  * the structured-output schema (``app.agents.state.CodeOutput``)
  * the visual style (``app.agents.styles`` — markdown + few-shot)

LangChain 1.x standard pattern:
    ``create_agent(model=chat_model, response_format=PydanticSchema, ...)``

    ``model``         — chat model (BaseChatModel, NOT a Runnable)
    ``tools``         — @tool-decorated callables
    ``system_prompt`` — single string (we concat base + chosen style)
    ``response_format`` — Pydantic schema for structured output

Switching visual style is a matter of passing a different ``style_id``.
The agent itself is rebuilt (lru_cache key includes style_id) so different
styles get isolated prompt templates.
"""
from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent

from app.agents.state import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID, STYLE_IDS, load_style
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.llm.client import get_llm


TOOLS = [validate_manim_code, render_manim_dryrun]


@lru_cache
def build_agent(style_id: str = DEFAULT_STYLE_ID):
    """Build the singleton agent for a given style.

    Returns a LangChain ``CompiledStateGraph``. Invoke with
    ``await agent.ainvoke({"messages": [...]})``. The structured
    ``CodeOutput`` lands in ``result["structured_response"]``.
    """
    style = load_style(style_id)
    llm = get_llm()
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=style.description,
        response_format=CodeOutput,
    )


__all__ = ["build_agent", "TOOLS", "STYLE_IDS"]
