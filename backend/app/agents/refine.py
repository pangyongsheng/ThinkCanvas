"""``refine`` — 多轮调整 LLM wrapper（无中间件、无落库）。

仅供 ``tests/agents/test_refine`` 校验；**生产入口**走 ``AgentService.run_refine``。

用户已经有了一个能跑的动画，我们让 LLM：

  * 保留 ``from manim import *`` 和 Scene 类名（除非用户明确说要改）
  * 只针对用户的调整要求做最小改动
  * 通过 CodeOutput 返回完整的新版本代码

喂给 LLM 的内容只有：
  * **上一版完整代码**（数据库里最新一条 assistant 消息的 code）
  * **历史上所有用户原话**（user role 的 content，按时间正序，限最近 6 条）
  * **本次调整指令**（不重复在 history 里，单独高亮）
  * **召回的 FewShot**（按 prompt 相似度，调用方传入）

不喂 assistant 历史回复 — 既省 token，渐进式需求也已经能从
"用户说过的话"里看出来。
"""
from __future__ import annotations

import logging
from typing import Sequence

from langchain_core.messages import HumanMessage

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.builder import build_agent
from app.agents.styles import DEFAULT_STYLE_ID
from app.db.models import FewShot


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
    user_history: list[str] | None = None,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 6,
    few_shots: Sequence[FewShot] = (),
) -> dict:
    """构建 refine agent 并跑 ``ainvoke``。

    返回 dict 形状：``{"code": str|None, "messages": [...]}``。

    生产路径不应使用本函数——调它不会落 ``agent_steps`` 表。
    生产入口请走 ``AgentService.run_refine``。
    """
    if not prev_code or not prev_code.strip():
        raise ValueError("refine.run_refine: prev_code is empty")
    if not instruction or not instruction.strip():
        raise ValueError("refine.run_refine: instruction is empty")

    agent = build_agent(
        style_id=style_id,
        extra_system_prompt=_SYSTEM_REFINE_PREAMBLE,
        few_shots=list(few_shots),
    )
    prompt_text = _build_refine_prompt(prev_code, instruction, user_history)
    return await invoke_with_recovery(
        agent,
        {"messages": [HumanMessage(content=prompt_text)]},
        max_iterations=max_iterations,
        label="agent.refine",
        style_id=style_id,
    )


__all__ = ["run_refine"]
