"""Tests for ``app.agents.few_shot_prompt``."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.few_shot_prompt import format_few_shot_block, with_few_shot_header


def _shot(id_: str, prompt: str, summary: str, style: str, code: str):
    row = MagicMock()
    row.id = id_
    row.prompt = prompt
    row.summary = summary
    row.style = style
    row.code = code
    return row


def test_empty_list_returns_empty():
    assert format_few_shot_block([]) == ""
    assert with_few_shot_header([]) == ""


def test_format_block_contains_all_fields():
    rows = [
        _shot("a", "求梯形面积", "梯形面积推导", "3b1b",
              "from manim import *\nclass T(Scene):\n    pass"),
    ]
    block = format_few_shot_block(rows)
    assert "### 例 1 · 3b1b" in block
    assert "**题目**: 求梯形面积" in block
    assert "**代码**:" in block
    assert "from manim import *" in block
    assert "class T(Scene):" in block


def test_format_multiple_shots_numbered():
    rows = [
        _shot("a", "p1", "s1", "3b1b", "c1"),
        _shot("b", "p2", "s2", "academic", "c2"),
    ]
    block = format_few_shot_block(rows)
    assert "### 例 1 · 3b1b" in block
    assert "### 例 2 · academic" in block


def test_with_header_adds_intro():
    rows = [_shot("a", "p", "s", "3b1b", "c")]
    block = with_few_shot_header(rows)
    assert block.startswith("## 以下是用户收藏的范例")
    assert "### 例 1" in block
