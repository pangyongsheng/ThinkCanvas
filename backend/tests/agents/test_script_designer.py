"""Script Designer agent + schema 测试。"""
from __future__ import annotations

from app.agents.script_designer import (
    Scene,
    SceneScript,
    build_script_designer_prompt,
    build_script_designer_user_message,
)


def test_scene_required_fields():
    s = Scene(
        index=0,
        duration_sec=8.0,
        description="屏幕上有一个蓝色圆",
        animation="从左滑入",
        text_overlays=["f(x) = x^2"],
        math_objects=["Circle", "Text"],
    )
    assert s.index == 0
    assert s.duration_sec == 8.0
    assert s.text_overlays == ["f(x) = x^2"]


def test_scene_defaults():
    s = Scene(
        index=0,
        duration_sec=5.0,
        description="x" * 10,
        animation="x" * 5,
    )
    assert s.text_overlays == []
    assert s.math_objects == []


def test_scene_duration_must_be_positive():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Scene(index=0, duration_sec=0, description="x" * 10, animation="x" * 5)


def test_scene_script_min_one_scene():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SceneScript(
            title="t",
            concept="c",
            total_duration_sec=10.0,
            style="3b1b",
            scenes=[],
        )


def test_scene_script_max_six_scenes():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SceneScript(
            title="t",
            concept="c",
            total_duration_sec=60.0,
            style="3b1b",
            scenes=[
                Scene(index=i, duration_sec=5.0, description="x" * 10, animation="x" * 5)
                for i in range(7)
            ],
        )


def test_scene_script_valid():
    s = SceneScript(
        title="矩阵 × 向量",
        concept="展示线性变换的几何意义",
        total_duration_sec=20.0,
        style="3b1b",
        scenes=[
            Scene(index=0, duration_sec=5.0, description="x" * 10, animation="x" * 5),
            Scene(index=1, duration_sec=10.0, description="x" * 10, animation="x" * 5),
        ],
    )
    assert len(s.scenes) == 2
    assert s.style == "3b1b"


def test_script_designer_prompt_mentions_json():
    p = build_script_designer_prompt()
    assert "JSON" in p
    assert "title" in p
    assert "scenes" in p


def test_script_designer_user_message_wraps_prompt():
    msg = build_script_designer_user_message("解释贝叶斯")
    assert "解释贝叶斯" in msg
    assert "[用户原始需求]" in msg
