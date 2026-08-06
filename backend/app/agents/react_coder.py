"""单次生成 agent 的公开入口。

这个模块是 HTTP 路由（``/generate``、``/conversations``）与 agent 栈之间
的薄壳。真正的逻辑在：

  * ``builder``       — agent 工厂
  * ``state``         — CodeOutput schema
  * ``styles``        — prompt 片段（风格 + few-shot）
  * ``agent_recovery`` — 模型输出异常时的多层兜底
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.builder import build_agent
from app.agents.styles import DEFAULT_STYLE_ID


async def run_agent(
    prompt: str,
    *,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 6,
) -> dict:
    """构建并调用标准的 LangChain agent。

    返回给 HTTP 层的 dict 形状：
        ``{"code": str|None, "tool_log": [...], "messages": [...]}``
    """
    agent = build_agent(style_id=style_id)
    return await invoke_with_recovery(
        agent,
        {"messages": [HumanMessage(content=prompt)]},
        max_iterations=max_iterations,
        label="agent.run",
        style_id=style_id,
    )


__all__ = ["run_agent"]
