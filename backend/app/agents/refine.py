"""Refine-mode agent: produce a new Manim version based on previous code.

Used by the multi-turn conversation flow. The user already has a working
animation; we ask the LLM to:

  * keep ``from manim import *`` and the Scene class name (unless told
    otherwise)
  * only change what the instruction asks for
  * return the full updated code via CodeOutput

Implementation deliberately reuses ``run_agent``'s extraction pipeline
(via ``react_coder._invoke_and_extract``) so the MiniMax thinking-block
fallback works identically here.
"""
from __future__ import annotations

import logging
from typing import Optional

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.agents.builder import TOOLS
from app.agents.state import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID, load_style
from app.agents.react_coder import _invoke_and_extract
from app.llm.client import get_llm


logger = logging.getLogger("thinkcanvas.agent.refine")


_SYSTEM_REFINE_PREAMBLE = (
    "你现在处于【精细调整模式】。用户已经有一个能跑的 Manim 动画版本，下面是上一版代码。"
    "请只针对用户提出的调整要求做最小改动，其余代码保持原样。硬性约束：\n"
    "1. 必须保留 `from manim import *` 头\n"
    "2. Scene 类名尽量沿用（除非用户明确说要改名）\n"
    "3. 公式或库函数若发生改动，相应 import 也保留\n"
    "4. 只输出完整新版本代码（CodeOutput{thought, code}），不要附加解释文字\n"
)


def _build_refine_prompt(prev_code: str, instruction: str) -> str:
    return (
        "[上一版代码]\n"
        "```python\n" + prev_code.rstrip() + "\n```\n\n"
        "[本次用户调整要求]\n" + instruction.strip()
    )


async def run_refine(
    prev_code: str,
    instruction: str,
    *,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 4,
) -> dict:
    """Build a one-shot agent that rewrites ``prev_code`` per ``instruction``.

    Returns the same shape as ``run_agent``::

        {"code": str|None, "tool_log": [...], "messages": [...]}

    The agent is built fresh on each call (no lru_cache) because the
    system prompt is per-style and the human message is dynamic.
    """
    if not prev_code.strip():
        raise ValueError("prev_code is empty — cannot refine")
    if not instruction.strip():
        raise ValueError("instruction is empty — nothing to refine")

    style = load_style(style_id)
    llm = get_llm()
    system_prompt = style.description + "\n\n" + _SYSTEM_REFINE_PREAMBLE
    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=system_prompt,
        response_format=CodeOutput,
    )

    prompt = _build_refine_prompt(prev_code, instruction)
    logger.info(
        "agent.refine start style=%s instruction=%r prev_len=%d",
        style_id,
        instruction[:80],
        len(prev_code),
    )
    result = await _invoke_and_extract(
        agent,
        {"messages": [HumanMessage(content=prompt)]},
        max_iterations=max_iterations,
        label="agent.refine",
        style_id=style_id,
    )
    logger.info(
        "agent.refine end code=%s tool_calls=%d",
        "OK" if result["code"] else "NONE",
        len(result["tool_log"]),
    )
    return result


__all__ = ["run_refine"]
