"""单次生成 agent 的公开入口。

这个模块是 HTTP 路由（``/generate``、``/conversations``）与 agent 栈之间
的薄壳。真正的逻辑在：

  * ``builder``         — agent 工厂
  * ``schemas``         — CodeOutput schema
  * ``styles``          — prompt 片段（风格 markdown）
  * ``retriever``       — 按 prompt 相似度召回 FewShot
  * ``few_shot_prompt`` — FewShot 列表 → system prompt 片段
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
    on_event=None,
) -> dict:
    """构建并调用标准的 LangChain agent。

    返回给 HTTP 层的 dict 形状：
        ``{"code": str|None, "tool_log": [...], "messages": [...]}``

    ``few_shots`` 由调用方（HTTP 入口）先调 ``retriever`` 召回后传入；
    这里只负责拼到 system prompt 里。
    """
    agent = build_agent(
        style_id=style_id,
        few_shots=list(few_shots),
    )
    result = await invoke_with_recovery(
        agent,
        {"messages": [HumanMessage(content=prompt)]},
        max_iterations=max_iterations,
        label="agent.run",
        style_id=style_id,
        on_event=on_event,
    )
    return result


__all__ = ["run_agent"]
