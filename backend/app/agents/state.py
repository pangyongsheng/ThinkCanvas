"""Structured-output schemas for the agent.

The standard LangChain pattern is to attach a Pydantic schema via
``llm.with_structured_output(SomeModel)``. The framework then guarantees
the LLM returns JSON conforming to that schema — no hand-written parser,
no fallback regex, no markdown-fence stripping.

Models
------
``CodeOutput``
    Final structured answer from the agent: a one-sentence ``thought``
    plus the complete Manim ``code`` body. Normalised to start at the
    ``from manim import *`` line so downstream validators / renderer can
    consume it directly.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CodeOutput(BaseModel):
    """Final structured answer: reasoning + runnable Manim code."""

    thought: str = Field(description="一句话思路或对上一次错误的反思")
    code: str = Field(description="从 'from manim import *' 开始的完整 Manim 代码")

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        """Drop anything before the first ``from manim import`` line."""
        lines = v.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("from manim import"):
                return "\n".join(lines[i:]).strip()
        return v.strip()


__all__ = ["CodeOutput"]
