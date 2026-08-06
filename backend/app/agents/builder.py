"""Agent 工厂 — 整个项目唯一调用 ``langchain.agents.create_agent`` 的地方。

它是这几块之间的标准衔接点：
  * LLM（由 ``app.llm.client.get_llm`` 提供，类型是 ChatOpenAI）
  * 工具集（``app.agents.tools``，普通的 ``@tool`` 装饰函数）
  * 结构化输出 schema（``app.agents.schemas.CodeOutput``）
  * 视觉风格（``app.agents.styles``，markdown + few-shot）

LangChain 1.x 标准写法：
    ``create_agent(model=chat_model, response_format=PydanticSchema, ...)``

    ``model``         — chat model（BaseChatModel，不是 Runnable）
    ``tools``         — @tool 装饰的可调用对象
    ``system_prompt`` — 单一字符串（base + 选中风格 + 可选额外片段拼接而成）
    ``response_format`` — 用于结构化输出的 Pydantic schema

切换视觉风格只需要传不同的 ``style_id``。每次会重新构建 agent
（lru_cache 的 key 包含 style_id 和 extra_system_prompt），不同配置
的 prompt 模板互相隔离。

注意：因为 ``get_llm()`` 每次会新建一个 ChatOpenAI 客户端，这里先
显式取一次，保证缓存命中后复用同一个 LLM 实例。
"""
from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent

from app.agents.schemas import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID, STYLE_IDS, load_style
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.llm.client import get_llm


TOOLS = [validate_manim_code, render_manim_dryrun]


@lru_cache
def build_agent(
    style_id: str = DEFAULT_STYLE_ID,
    extra_system_prompt: str = "",
):
    """构建指定 (style, extra_prompt) 组合的单例 agent。

    参数 ``extra_system_prompt`` 用于多轮调整模式：
    ``refine.py`` 会在风格 markdown 后面追加一段【精细调整模式】的
    提示词，让同一套 agent 工厂也能产出"重写旧代码"版本的 agent。

    cache key = (style_id, extra_system_prompt)，所以不同风格的、
    或者同风格但 extra_prompt 不同的 agent 都会被分别缓存复用。

    返回 LangChain 的 ``CompiledStateGraph``。调用方式：
    ``await agent.ainvoke({"messages": [...]})``。
    结构化的 ``CodeOutput`` 会落在 ``result["structured_response"]``。
    """
    style = load_style(style_id)
    llm = get_llm()
    system_prompt = style.description
    if extra_system_prompt:
        system_prompt = system_prompt + "\n\n" + extra_system_prompt
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=system_prompt,
        response_format=CodeOutput,
    )


__all__ = ["build_agent", "TOOLS", "STYLE_IDS"]
