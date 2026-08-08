"""``react_coder`` — 单次 LLM 提码 wrapper（无中间件、无落库）。

仅供 ``tests/agents/test_*_fallback`` / ``test_coder`` 校验
``invoke_with_recovery`` 兜底链使用；**生产入口**走 ``AgentService``，
由 ``AgentPersistenceMiddleware`` 自动落 ``agent_steps`` / messages。

真正的逻辑在：
  * ``builder``         — agent 工厂
  * ``schemas``         — CodeOutput schema
  * ``styles``          — prompt 片段（风格 markdown）
  * ``agent_recovery``  — 模型输出异常时的多层兜底
"""
from __future__ import annotations

from typing import Sequence

from langchain_core.messages import HumanMessage

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.builder import build_agent
from app.agents.styles import DEFAULT_STYLE_ID
from app.db.models import FewShot


async def run_agent(
    prompt: str,
    *,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 6,
    few_shots: Sequence[FewShot] = (),
) -> dict:
    """构建并调用标准的 LangChain agent。

    返回 dict 形状：``{"code": str|None, "messages": [...]}``。

    生产路径不应使用本函数——调它不会落 ``agent_steps`` 表。
    """
    agent = build_agent(
        style_id=style_id,
        few_shots=list(few_shots),
    )
    return await invoke_with_recovery(
        agent,
        {"messages": [HumanMessage(content=prompt)]},
        max_iterations=max_iterations,
        label="agent.run",
        style_id=style_id,
    )


__all__ = ["run_agent"]
