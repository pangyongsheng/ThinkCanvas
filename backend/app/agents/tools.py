"""ReAct agent 可调用的 LangChain tools。

每个函数用 ``@tool`` 装饰；LangChain 会把 docstring + 参数类型解析成 LLM
可以选择的 JSON schema。

agent 流程：
    1. LLM 生成代码
    2. LLM 调用 ``validate_manim_code(code)`` -> ``OK`` 或 ``errors: ...``
    3. LLM 调用 ``render_manim_dryrun(code)`` -> ``rendered ok: <路径>`` 或 stderr
    4. LLM 决定下一步（修复、重试或结束）
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
