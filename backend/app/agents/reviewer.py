"""Reviewer agent — Coder 写完代码后做独立审查。

P2 范围：纯 LLM（无工具），给定代码 + 可选 review feedback 上下文，
输出结构化 ``CodeReview{ok, feedback}``。Supervisor 根据 ok 决定是
收工还是让 Coder 重写。

审查维度（v1）：
  1. Manim API 用对没有（import / Scene / construct / play / wait）
  2. 危险调用没有（os / subprocess / 死循环 / 网络）
  3. 代码结构合理（一段代码完整、不截断）

不审查（留给人工）：
  * 数学概念是否传达准确 — LLM 难判，让用户自己看视频
  * 视觉风格是否符合 — 同上
"""
from __future__ import annotations

from pydantic import BaseModel, Field


REVIEWER_SYSTEM_PROMPT = (
    "你是 ThinkCanvas 的代码审查员。\n"
    "\n"
    "职责：拿到 Coder 写的 Manim Python 代码，做客观技术审查。\n"
    "\n"
    "只审查这些：\n"
    "  1. Manim API 用对没有（必须 from manim import *；必须有 class X(Scene)\n"
    "     + def construct(self)；play() / wait() / FadeIn 等调用顺序合理）\n"
    "  2. 没有危险调用（os.* / subprocess.* / while True: / open() / 网络）\n"
    "  3. 代码结构完整不截断（最后有 self.wait() 或类似收尾）\n"
    "  4. AST 层面没有明显语法错误\n"
    "\n"
    "不要审查：\n"
    "  * 数学概念 / 视觉表达 — 用户自己判断\n"
    "  * 风格偏好 — 风格由 system prompt 决定\n"
    "\n"
    "【输出格式 — 严格 JSON，不要其他文字】\n"
    "你必须只输出一个 JSON 对象，不要任何 JSON 之外的文字。\n"
    "不要 OK 看着没问题、不要 markdown 包裹、不要多个对象。\n"
    "\n"
    "格式：\n"
    "  {\"ok\": true, \"feedback\": \"\"}\n"
    "  {\"ok\": false, \"feedback\": \"第 X 行 Y 有问题，应该改成 Z\"}\n"
    "\n"
    "ok=true 时 feedback 留空字符串。\n"
    "ok=false 时 feedback 写清楚哪里错、应该改成什么，不超过 200 字。\n"
    "\n"
    "如果你输出非 JSON（普通文字 / ```json 包裹 / 多个对象），系统\n"
    "会 fallback 成通过 — 你的修改建议就丢了。所以严格只输出一个\n"
    "JSON 对象。"
)


class CodeReview(BaseModel):
    """Reviewer 审查结果。"""

    ok: bool = Field(description="True = 通过；False = 需要 Coder 重写")
    feedback: str = Field(
        default="",
        description="ok=false 时写具体修改建议；ok=true 时可留空",
    )


def build_reviewer_prompt() -> str:
    """Reviewer 自己的 system prompt。"""
    return REVIEWER_SYSTEM_PROMPT


def build_reviewer_user_message(code: str, previous_feedback: str = "") -> str:
    """拼 Reviewer 收到的 user message。

    结构：
      1. [上次审查反馈]（如果有 — 第二轮 Reviewer 看到的是修正后的代码，
         给 feedback 让它能判断"修对了没"）
      2. [待审查代码]
    """
    parts: list[str] = []
    if previous_feedback:
        parts.append(f"[上次审查反馈]\n{previous_feedback.strip()}")
    parts.append("[待审查代码]\n```python\n" + code.rstrip() + "\n```")
    return "\n\n".join(parts)


__all__ = [
    "CodeReview",
    "REVIEWER_SYSTEM_PROMPT",
    "build_reviewer_prompt",
    "build_reviewer_user_message",
]
