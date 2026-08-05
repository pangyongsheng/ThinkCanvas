"""LangGraph ReAct agent — uses the standard ``langgraph.prebuilt.create_react_agent``.

This is the **canonical** LangChain/LangGraph agent pattern. Compared to a
hand-rolled loop, this approach:

    - Lets the LLM itself decide when to call which tool
    - Routes ``tool_calls`` through LangGraph's StateGraph automatically
    - Standard pattern that appears in LangChain / LangGraph docs and courses

Usage::

    from app.agents.react_coder import build_agent, run

    agent = build_agent(llm=my_llm, max_iterations=6)
    result = await run(agent, "冒泡排序")
    print(result["code"])
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.agents.tools import render_manim_dryrun, validate_manim_code


SYSTEM_PROMPT = """你是 ThinkCanvas 的 Manim 代码生成助手。

# 工具
- ``validate_manim_code(code: str)``: 必须先调用，检查代码合法性
- ``render_manim_dryrun(code: str)``: 验证通过后才能调用，实际跑 manim；失败时把 stderr 返回给你

# 工作流（按顺序）
1. 在 thought 里讲清楚思路，生成代码
2. 调用 ``validate_manim_code`` 验证语法
3. 验证通过后调用 ``render_manim_dryrun`` 实跑
4. 报错就读错误 → 改代码 → 再 validate → 再 render
5. 跑通后 final answer（在 content 里写最终代码）

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


def build_agent(llm, *, max_iterations: int = 6):
    """Build a LangGraph ReAct agent with our tools.

    The agent's decision flow (call tool / call LLM / end) is handled entirely
    by the LangGraph state machine; we just inject our tools + system prompt.
    """
    return create_react_agent(
        llm,
        tools=TOOLS,
        state_modifier=SYSTEM_PROMPT,
    )


async def run(agent, prompt: str, *, max_iterations: int = 6) -> dict:
    """Run the agent and return a structured result dict.

    Returns ``{"code": str|None, "tool_log": [...], "messages": [...]}``.
    """
    # Apply the recursion_limit at invoke time, not at build time
    config = {"recursion_limit": max_iterations * 4 + 1}
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config=config,
    )

    messages = result.get("messages", [])
    final_code: str | None = None
    tool_log: list[dict] = []

    for msg in messages:
        if isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
            if content and not msg.tool_calls:
                final_code = _extract_code(content) or final_code
            for tc in (msg.tool_calls or []):
                tool_log.append(
                    {
                        "tool": tc.get("name"),
                        "args": {k: str(v)[:200] for k, v in (tc.get("args") or {}).items()},
                        "id": tc.get("id"),
                    }
                )
        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tool_log and tool_log[-1].get("id") == tc_id:
                tool_log[-1]["result"] = str(msg.content)[:1000]

    return {
        "code": final_code,
        "tool_log": tool_log,
        "messages": [str(getattr(m, "content", m)) for m in messages],
    }


def _extract_code(content: str) -> str | None:
    """Pull a Python code block out of an AIMessage final answer."""
    text = content.strip()
    if "```" in text:
        for block in text.split("```"):
            chunk = block.strip()
            if chunk.startswith("python"):
                chunk = chunk[len("python"):].strip()
            if "from manim import" in chunk:
                lines = chunk.split("\n")
                for i, line in enumerate(lines):
                    if line.strip().startswith("from manim import"):
                        return "\n".join(lines[i:]).strip()
    if "from manim import" in text:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("from manim import"):
                return "\n".join(lines[i:]).strip()
    return None
