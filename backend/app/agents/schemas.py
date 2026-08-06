"""Agent 的结构化输出 schema。

LangChain 的标准做法是把一个 Pydantic schema 通过
``llm.with_structured_output(SomeModel)`` 挂上去。框架保证 LLM 返回
符合该 schema 的 JSON — 不用手写解析、不需要 fallback 正则、
也不需要剥 markdown 栅栏。

Models
------
``CodeOutput``
    agent 的最终结构化答案：一句话的 ``thought`` 加完整的 Manim ``code``
    代码体。会被规范化成从 ``from manim import *`` 开头，方便后续的
    校验器和渲染器直接消费。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CodeOutput(BaseModel):
    """最终结构化答案：思路 + 可运行的 Manim 代码。"""

    thought: str = Field(description="一句话思路或对上一次错误的反思")
    code: str = Field(description="从 'from manim import *' 开始的完整 Manim 代码")

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        """把第一个 ``from manim import`` 之前的内容全部丢掉。"""
        lines = v.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("from manim import"):
                return "\n".join(lines[i:]).strip()
        return v.strip()


__all__ = ["CodeOutput"]
