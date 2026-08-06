"""风格注册表 — style_id → 系统 prompt 描述的映射。

一个风格就是一个 markdown 文件，包含：
  * 视觉指南（配色 / 尺寸 / 节奏）
  * 一段 few-shot 代码示例

agent 收到的系统 prompt 是 base 文件 + 选中风格文件拼接而成。
我们不在 Python 里硬编码风格 — 新增一个风格只是在
``shared/prompts/styles/`` 目录里丢一个 .md 文件。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_STYLES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "shared"
    / "prompts"
    / "styles"
)
_BASE_FILE = _STYLES_DIR / "base.md"

# 规范列表 — 与前端下拉框保持同步。
STYLE_IDS: tuple[str, ...] = ("3b1b", "minimal", "academic")
DEFAULT_STYLE_ID = "3b1b"


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    description: str  # 完整的 markdown 内容（base + 风格特化）


# 友好显示名（前端用）。
STYLE_LABELS: dict[str, str] = {
    "3b1b": "3Blue1Brown（深色鲜艳）",
    "minimal": "Minimal（深色极简）",
    "academic": "Academic（明亮学术）",
}


def load_style(style_id: str) -> Style:
    """按 id 加载风格；未知 id 回退到 ``DEFAULT_STYLE_ID``。

    只有 base 文件缺失才会抛 FileNotFoundError — 这是编程错误而不是用户错误。
    """
    if not _BASE_FILE.exists():
        raise FileNotFoundError(f"base style file missing: {_BASE_FILE}")

    if style_id not in STYLE_IDS:
        style_id = DEFAULT_STYLE_ID

    style_file = _STYLES_DIR / f"{style_id}.md"
    if not style_file.exists():
        # 允许的 id 但文件缺失 — 也回退。
        style_id = DEFAULT_STYLE_ID
        style_file = _STYLES_DIR / f"{style_id}.md"

    description = _BASE_FILE.read_text(encoding="utf-8") + "\n\n" + style_file.read_text(
        encoding="utf-8"
    )

    return Style(
        id=style_id,
        name=STYLE_LABELS.get(style_id, style_id),
        description=description,
    )


__all__ = [
    "Style",
    "load_style",
    "STYLE_IDS",
    "STYLE_LABELS",
    "DEFAULT_STYLE_ID",
]
