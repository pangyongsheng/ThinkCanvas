"""Tests for the style registry."""
from __future__ import annotations

import pytest

from app.agents.styles import (
    DEFAULT_STYLE_ID,
    STYLE_IDS,
    STYLE_LABELS,
    load_style,
)


def test_default_style_id_is_in_canonical_list():
    assert DEFAULT_STYLE_ID in STYLE_IDS


def test_all_styles_have_labels():
    for sid in STYLE_IDS:
        assert sid in STYLE_LABELS


@pytest.mark.parametrize("style_id", list(STYLE_IDS))
def test_load_each_style_returns_non_empty_description(style_id):
    s = load_style(style_id)
    assert s.id == style_id
    assert s.description.strip()
    # base + style specific concatenated
    assert "# 硬性约束" in s.description  # from base.md


def test_load_unknown_id_falls_back_to_default():
    s = load_style("does-not-exist")
    assert s.id == DEFAULT_STYLE_ID


@pytest.mark.parametrize("style_id", list(STYLE_IDS))
def test_each_style_has_fewshot_python_block(style_id):
    s = load_style(style_id)
    assert "```python" in s.description, f"{style_id} style missing few-shot"


def test_academic_style_references_white_background():
    s = load_style("academic")
    assert "#FFFFFF" in s.description or "white" in s.description.lower()
    # academic allows LaTeX
    assert "MathTex" in s.description


def test_minimal_style_forbids_color():
    s = load_style("minimal")
    assert "WHITE" in s.description
    assert "BLUE" not in s.description or "绝对不要" in s.description


def test_3b1b_style_uses_default_colors():
    s = load_style("3b1b")
    assert "BLUE" in s.description and "YELLOW" in s.description
