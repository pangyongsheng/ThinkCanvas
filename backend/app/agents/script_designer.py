"""Script Designer agent — 把用户的模糊需求拆成结构化动画脚本。

P3 范围：纯 LLM（无工具），给定用户需求，输出 ``SceneScript`` —
含总时长 / 风格建议 / 多个分镜（视觉描述 / 动画 / 文字标注 /
数学对象）。用户看完确认后，Coder 基于这份脚本写 Manim 代码。

不做什么：
  * 不写 Manim 代码（留给 Coder）
  * 不审代码（Reviewer 干这事）
  * 不解决模糊需求（用户看到脚本不对可以自己改）
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# 提示词里用 中文引号 “” 避免和 Python 字符串边界冲突
SCRIPT_DESIGNER_PROMPT = (
    "你是 ThinkCanvas 的动画脚本设计师。\n"
    "\n"
    "职责：拿到用户的模糊 / 复杂需求，拆成 2-4 个分镜，每个分镜\n"
    "含视觉描述 / 关键动画 / 文字标注 / 数学对象。\n"
    "\n"
    "什么时候出脚本（你的工作场景）：\n"
    "  * 用户的概念比较抽象（比如 “解释傅里叶变换的物理意义”）\n"
    "  * 用户没明确说怎么做（比如 “做个微积分”）\n"
    "  * 内容比较长 / 复杂（比如 “展示贝叶斯定理 + 一个例子”）\n"
    "  * 用户希望控制细节（比如 “分三段讲，第一段 ...”）\n"
    "\n"
    "什么时候不需要出脚本（Supervisor 会直接调 Coder）：\n"
    "  * 明确单一的算法（比如 “冒泡排序”、“二分查找”、“图 BFS”）\n"
    "  * 用户给了具体步骤（比如 “先建一个圆、再画条切线”）\n"
    "\n"
    "分镜设计原则：\n"
    "  1. 每段视觉描述要具体到屏幕上会出现什么，不要抽象描述\n"
    "  2. 关键动画要明确写怎么动（淡入 / 平移 / 缩放 / 旋转）\n"
    "  3. 文字标注是屏幕上的数学符号 / 公式 / 标签，不是旁白\n"
    "  4. 数学对象是 Manim 里要构造的元素（图 / 向量 / 坐标轴 / 公式）\n"
    "  5. 总时长控制在 30 秒以内（首屏要 30s 内出视频）\n"
    "\n"
    "【输出格式 — 严格 JSON】\n"
    "你必须只输出一个 JSON 对象，不要任何 JSON 之外的文字。\n"
    "\n"
    "格式：\n"
    "{\n"
    '  "title": "一句话标题",\n'
    '  "concept": "一句话说清要表达的数学点",\n'
    '  "total_duration_sec": 25,\n'
    '  "style": "3b1b 或 academic 或 minimal",\n'
    '  "scenes": [\n'
    "    {\n"
    '      "index": 0,\n'
    '      "duration_sec": 8.0,\n'
    '      "description": "屏幕上出现什么（具体到颜色 / 位置 / 形状）",\n'
    '      "animation": "怎么动（顺序 + 节奏）",\n'
    '      "text_overlays": ["屏幕上显示的公式 / 标签"],\n'
    '      "math_objects": ["Manim 里要构造的元素"]\n'
    "    }\n"
    "  ]\n"
    "}"
)


class Scene(BaseModel):
    """一段分镜。"""

    index: int = Field(description="0-based 序号")
    duration_sec: float = Field(gt=0.0, le=30.0, description="这一镜时长（秒）")
    description: str = Field(
        min_length=5,
        description="视觉描述：屏幕上会出现什么（具体到颜色 / 位置 / 形状）",
    )
    animation: str = Field(
        min_length=3,
        description="动画：怎么动（顺序 + 节奏）",
    )
    text_overlays: list[str] = Field(
        default_factory=list,
        description="屏幕上显示的公式 / 标签",
    )
    math_objects: list[str] = Field(
        default_factory=list,
        description="Manim 里要构造的元素（图 / 向量 / 坐标轴 / 公式）",
    )


class SceneScript(BaseModel):
    """一整个动画脚本（一个或多个分镜）。"""

    title: str = Field(min_length=1, max_length=120, description="一句话标题")
    concept: str = Field(min_length=1, max_length=300, description="一句话说清要表达的数学点")
    total_duration_sec: float = Field(gt=0.0, le=60.0, description="总时长（秒）")
    style: str = Field(
        default="3b1b",
        description="视觉风格：3b1b / academic / minimal",
    )
    scenes: list[Scene] = Field(
        min_length=1, max_length=6,
        description="分镜列表（1-6 个）",
    )


def build_script_designer_prompt() -> str:
    return SCRIPT_DESIGNER_PROMPT


def build_script_designer_user_message(user_prompt: str) -> str:
    """拼 Script Designer 收到的 user message。"""
    return f"[用户原始需求]\n{user_prompt.strip()}"


__all__ = [
    "Scene",
    "SceneScript",
    "SCRIPT_DESIGNER_PROMPT",
    "build_script_designer_prompt",
    "build_script_designer_user_message",
]
