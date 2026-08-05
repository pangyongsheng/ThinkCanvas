"""LangChain tools the ReAct agent can call.

Each function is decorated with ``@tool``; LangChain parses the docstring +
parameter types into a JSON schema the LLM can choose to call.

The agent flow becomes:
    1. LLM generates code
    2. LLM calls ``validate_manim_code(code)`` -> "OK" or "errors: ..."
    3. LLM calls ``render_manim_dryrun(code)`` -> "rendered ok: path" or stderr
    4. LLM decides what to do next (fix, retry, or stop)
"""
from __future__ import annotations

from langchain_core.tools import tool

from app.renderers.manim import render_code
from app.tools.validator import validate_code


@tool
async def validate_manim_code(code: str) -> str:
    """验证 Manim Python 代码是否合法（render 之前必调）。

    检查项：
      - 必须含 ``from manim import *``
      - 不能用 ``os`` / ``subprocess`` / 网络 / 危险调用
      - 必须有一个 Scene 子类 + ``construct(self)`` 方法
      - AST 必须能解析

    输入：完整 Python 代码字符串。
    返回：``OK`` 或 ``errors: <错误描述>``。
    """
    ok, error = validate_code(code)
    return "OK" if ok else f"errors: {error}"


@tool
async def render_manim_dryrun(code: str) -> str:
    """真跑 manim，验证运行时是否正确（比 validate 慢，约 10-30 秒）。

    必须先调过 ``validate_manim_code``。

    输入：完整 Python 代码字符串。
    返回：
      - 成功 → ``rendered ok: <绝对路径>``
      - 失败 → ``render error: <stderr 末段>``
    """
    result = await render_code(code)
    if result.error or not result.video_path:
        return f"render error: {result.error or 'no video produced'}"
    return f"rendered ok: {result.video_path}"
