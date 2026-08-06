"""ReAct-style agent entry point — ``create_agent`` standard.

Wraps the agent factory with a thin async helper that:

  * calls the canonical ``create_agent`` agent
  * extracts the structured ``CodeOutput`` from the final state
  * returns a compact dict the HTTP layer can serialise

No hand-rolled tool loop, no markdown-fence parsing, no messages-walking
to recover ``tool_calls``. The agent is built by
``app.agents.builder.build_agent()`` and the structured response comes
straight from ``state["structured_response"]`` after ``ainvoke``.
"""
from __future__ import annotations

from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.builder import build_agent


async def run_agent(prompt: str, *, max_iterations: int = 6) -> dict:
    """Build + invoke the standard LangChain agent.

    Returns
    -------
    dict
        ``{"code": str|None, "tool_log": [...], "messages": [...]}``
    """
    agent = build_agent()
    # LangGraph's ainvoke expects a typed RunnableConfig, not a plain dict.
    # The shape is correct at runtime; we just satisfy the type checker.
    config = cast(
        RunnableConfig,
        {"recursion_limit": max_iterations * 4 + 1},
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config=config,
    )

    structured = result.get("structured_response")
    messages = result.get("messages", [])

    tool_log: list[dict] = []
    final_code = None

    if structured is not None:
        final_code = structured.code

    for msg in messages:
        for tc in (getattr(msg, "tool_calls", None) or []):
            tool_log.append(
                {
                    "tool": tc.get("name"),
                    "args": {k: str(v)[:200] for k, v in (tc.get("args") or {}).items()},
                    "id": tc.get("id"),
                }
            )

    return {
        "code": final_code,
        "tool_log": tool_log,
        "messages": [str(getattr(m, "content", m)) for m in messages],
    }


__all__ = ["run_agent"]
