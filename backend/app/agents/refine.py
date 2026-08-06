"""精细调整模式 agent：基于上一版代码产出新的 Manim 版本。

用在多轮对话流程中。用户已经有了一个能跑的动画，我们让 LLM：

  * 保留 ``from manim import *`` 和 Scene 类名（除非用户明确说要改）
  * 只针对用户的调整要求做最小改动
  * 通过 CodeOutput 返回完整的新版本代码

喂给 LLM 的内容只有：
  * **上一版完整代码**（数据库里最新一条 assistant 消息的 code）
  * **历史上所有用户原话**（user role 的 content，按时间正序）
  * **本次调整指令**（不重复在 history 里，单独高亮）

不喂 assistant 历史回复 — 既省 token，渐进式需求也已经能从
"用户说过的话"里看出来。

实现上直接复用 ``run_agent`` 的提码流水线（通过
``agent_recovery.invoke_with_recovery``），这样 MiniMax thinking-block
兜底逻辑在两种模式下行为一致。

agent 本身也通过 ``builder.build_agent(..., extra_system_prompt=...)``
创建并缓存，不再单独 ``create_agent``，避免项目里出现"两个 agent
工厂路径"的隐患。
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.builder import build_agent
from app.agents.styles import DEFAULT_STYLE_ID
logger = logging.getLogger("thinkcanvas.agent.refine")


_SYSTEM_REFINE_PREAMBLE = (
    "你现在处于【精细调整模式】。用户已经有一个能跑的 Manim 动画版本，下面是上一版代码。"
    "请只针对用户提出的调整要求做最小改动，其余代码保持原样。硬性约束：\n"
    "1. 必须保留 `from manim import *` 头\n"
    "2. Scene 类名尽量沿用（除非用户明确说要改名）\n"
    "3. 公式或库函数若发生改动，相应 import 也保留\n"
    "4. 只输出完整新版本代码（CodeOutput{thought, code}），不要附加解释文字\n"
)


def _build_refine_prompt(
    prev_code: str,
    instruction: str,
    user_history: list[str] | None = None,
) -> str:
    """拼装 user message。

    结构（按顺序）：
      1. [历史用户指令] — 之前所有轮次的用户原话（如果有）
      2. [上一版代码]   — 上一轮 assistant 的完整 code
      3. [本次用户调整要求] — 当前 instruction（单独高亮，不混进 history）
    """
    parts: list[str] = []
    if user_history:
        bullet = "\n".join(f"- {h}" for h in user_history)
        parts.append(f"[历史用户指令]\n{bullet}")
    parts.append(
        "[上一版代码]\n"
        "```python\n" + prev_code.rstrip() + "\n```"
    )
    parts.append("[本次用户调整要求]\n" + instruction.strip())
    return "\n\n".join(parts)


async def run_refine(
    prev_code: str,
    instruction: str,
    *,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 4,
    user_history: list[str] | None = None,
) -> dict:
    """构建一次性 agent，按 ``instruction`` 重写 ``prev_code``。

    返回与 ``run_agent`` 相同形状::

        {"code": str|None, "tool_log": [...], "messages": [...]}

    agent 通过 ``build_agent(style_id, extra_system_prompt=...)`` 获取，
    同 (style_id, preamble) 组合会被 lru_cache 复用。

    ``user_history`` 是按时间正序的之前用户原话列表（不含本轮 instruction），
    用于让 LLM 理解用户的渐进式调整意图。
    """
    if not prev_code.strip():
        raise ValueError("prev_code is empty — cannot refine")
    if not instruction.strip():
        raise ValueError("instruction is empty — nothing to refine")

    agent = build_agent(
        style_id=style_id,
        extra_system_prompt=_SYSTEM_REFINE_PREAMBLE,
    )

    prompt = _build_refine_prompt(prev_code, instruction, user_history)
    logger.info(
        "agent.refine start style=%s instruction=%r prev_len=%d",
        style_id,
        instruction[:80],
        len(prev_code),
    )
    result = await invoke_with_recovery(
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
