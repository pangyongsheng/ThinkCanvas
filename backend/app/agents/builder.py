"""Agent factory — the only place that calls ``langchain.agents.create_agent``.

This module is the canonical seam between:
  * the LLM (delivered by ``app.llm.client.get_llm`` — typed as ChatOpenAI)
  * the tools (``app.agents.tools`` — plain ``@tool``-decorated functions)
  * the structured-output schema (``app.agents.state.CodeOutput``)

LangChain 1.x standard pattern:
    ``create_agent(model=chat_model, response_format=PydanticSchema, ...)``

    ``model``        — the chat model (must be a BaseChatModel, NOT a Runnable)
    ``response_format`` — the Pydantic schema for structured output
    ``tools``        — list of @tool-decorated callables
    ``system_prompt``— system message

No hand-written loops, no provider-specific code. Everything else in the
codebase just calls ``build_agent()`` and invokes the result.
"""
from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent

from app.agents.state import CodeOutput
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.llm.client import get_llm


SYSTEM_PROMPT = """你是 ThinkCanvas 的 Manim 代码生成助手。

# 工具
- ``validate_manim_code(code: str)``: 必须先调用，检查代码合法性
- ``render_manim_dryrun(code: str)``: 验证通过后才能调用，实际跑 manim；失败时把 stderr 返回给你

# 工作流（按顺序）
1. 在 thought 里讲清楚思路，生成代码
2. 调用 ``validate_manim_code`` 验证语法
3. 验证通过后调用 ``render_manim_dryrun`` 实跑
4. 报错就读错误 → 改代码 → 再 validate → 再 render
5. 跑通后输出最终 ``CodeOutput{thought, code}``

# 硬性约束（违反视为失败）
1. 导入：只允许 ``from manim import *``，禁止其他导入
2. 类结构：必须定义 ``class SceneName(Scene)``，方法名 ``construct``
3. 无 LaTeX：用 ``Text()`` 代替 ``MathTex()`` / ``Tex()``
4. 无 IO：禁止文件读写、网络请求、``os`` / ``subprocess`` / ``open``
5. 无循环炸弹：避免 ``while True``
6. 自包含：不依赖外部资源

# 风格
- 默认黑底（Manim 默认）
- 主色 BLUE / YELLOW / GREEN / RED
- 总时长 < 30 秒
"""


TOOLS = [validate_manim_code, render_manim_dryrun]


@lru_cache
def build_agent():
    """Build the singleton ReAct-style agent.

    Returns a LangChain ``CompiledStateGraph`` produced by
    ``langchain.agents.create_agent``. Invoke with
    ``await agent.ainvoke({"messages": [...]})``.

    The final structured ``CodeOutput`` is available at
    ``result["structured_response"]`` after ``ainvoke``.
    """
    llm = get_llm()
    return create_agent(
        model=llm,                       # chat model — NOT a Runnable/with_structured_output
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        response_format=CodeOutput,      # LangChain 1.x standard hook
    )


__all__ = ["build_agent", "SYSTEM_PROMPT", "TOOLS"]
