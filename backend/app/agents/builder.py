"""Agent 工厂 — 整个项目唯一调用 ``langchain.agents.create_agent`` 的地方。

它是这几块之间的标准衔接点：
  * LLM（由 ``app.llm.client.get_llm`` 提供，类型是 ChatOpenAI）
  * 工具集（``app.agents.tools``，普通的 ``@tool`` 装饰函数）
  * 结构化输出 schema（``app.agents.schemas.CodeOutput``）
  * 视觉风格（``app.agents.styles``，markdown + few-shot）
  * 召回的 FewShot（``app.agents.retriever`` + ``few_shot_prompt``）

LangChain 1.x 标准写法：
    ``create_agent(model=chat_model, response_format=PydanticSchema, ...)``

    ``model``         — chat model（BaseChatModel，不是 Runnable）
    ``tools``         — @tool 装饰的可调用对象
    ``system_prompt`` — 单一字符串
                       （base + 选中风格 + 可选 extra + 召回 few-shot）
    ``response_format`` — 用于结构化输出的 Pydantic schema
"""
from __future__ import annotations

from typing import Sequence

from langchain.agents import create_agent

from app.agents.few_shot_prompt import with_few_shot_header
from app.agents.schemas import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID, STYLE_IDS, load_style
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.db.models import FewShot
from app.llm.client import get_llm


TOOLS = [validate_manim_code, render_manim_dryrun]


def _compose_system_prompt(
    *,
    style_id: str,
    extra_system_prompt: str,
    few_shots: Sequence[FewShot],
) -> str:
    """按 style + extra + few_shots 拼出最终 system prompt。"""
    parts: list[str] = [load_style(style_id).description]
    if extra_system_prompt:
        parts.append(extra_system_prompt)
    fs_block = with_few_shot_header(list(few_shots))
    if fs_block:
        parts.append(fs_block)
    return "\n\n".join(parts)


def build_agent(
    *,
    style_id: str = DEFAULT_STYLE_ID,
    extra_system_prompt: str = "",
    few_shots: Sequence[FewShot] = (),
    middleware: Sequence = (),
):
    """构建 agent。AgentService 唯一调用。

    不缓存 CompiledStateGraph — LangChain 构建本身是秒级，prompt
    字符串每次都不同（few-shot 召回随用户输入变化），缓存命中率
    太低，没有必要。LLM 客户端仍走 ``get_llm()`` 单例复用。

    参数：
      * style_id             — 风格 id
      * extra_system_prompt  — refine 模式追加的"精细调整"提示词
      * few_shots            — 召回的 FewShot 列表，按相似度倒序
      * middleware           — LangChain 中间件列表（落库 / SSE 等）

    中间件：调用方传已经按 session 注入 DAO 的实例；本函数只做挂载，
    不参与 DB 写入。``AgentPersistenceMiddleware`` 是默认推荐挂载项，
    但本函数不强制——便于测试场景替换 mock。
    """
    system_prompt = _compose_system_prompt(
        style_id=style_id,
        extra_system_prompt=extra_system_prompt,
        few_shots=few_shots,
    )
    return create_agent(
        model=get_llm(),
        tools=TOOLS,
        system_prompt=system_prompt,
        response_format=CodeOutput,
        middleware=list(middleware),
    )


__all__ = ["build_agent", "TOOLS", "STYLE_IDS"]
