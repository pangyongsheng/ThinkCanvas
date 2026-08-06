"""Tests for the few_shots storage helpers."""
from __future__ import annotations

from app.db.models import Conversation, FewShot
from app.storage.few_shots import (
    _create_few_shot_sync,
    _list_few_shots_sync,
)


def _new_conv(s, conv_id="c1"):
    s.add(Conversation(id=conv_id, title="t", style="3b1b", user_id="u1"))
    s.commit()


def test_create_persists_required_fields(session):
    row = _create_few_shot_sync(
        session,
        prompt="冒泡排序",
        code="from manim import *\nclass Foo(Scene): pass",
        summary="冒泡排序可视化：两两比较交换",
        style="3b1b",
    )
    assert isinstance(row, FewShot)
    assert row.id and len(row.id) == 26
    assert row.prompt == "冒泡排序"
    assert row.code.startswith("from manim import *")
    assert row.summary == "冒泡排序可视化：两两比较交换"
    assert row.style == "3b1b"


def test_create_with_provenance(session):
    _new_conv(session)
    row = _create_few_shot_sync(
        session,
        prompt="x",
        code="from manim import *\nclass Y(Scene): pass",
        summary="展示 X 动画",
        style="academic",
        source_conversation_id="c1",
        source_message_id="m1",
    )
    assert row.source_conversation_id == "c1"
    assert row.source_message_id == "m1"


def test_list_returns_newest_first(session):
    for i in range(3):
        _create_few_shot_sync(
            session, prompt=f"p{i}", code="code", summary=f"s{i}", style="3b1b"
        )
    rows = _list_few_shots_sync(session)
    assert [r.prompt for r in rows] == ["p2", "p1", "p0"]


def test_list_filters_by_style(session):
    _create_few_shot_sync(session, prompt="a", code="x", summary="sa", style="3b1b")
    _create_few_shot_sync(session, prompt="b", code="x", summary="sb", style="academic")
    _create_few_shot_sync(session, prompt="c", code="x", summary="sc", style="3b1b")

    rows = _list_few_shots_sync(session, style="3b1b")
    assert {r.prompt for r in rows} == {"a", "c"}

    rows = _list_few_shots_sync(session, style="academic")
    assert {r.prompt for r in rows} == {"b"}

    rows = _list_few_shots_sync(session, style="minimal")
    assert rows == []


def test_list_respects_limit(session):
    for i in range(5):
        _create_few_shot_sync(
            session, prompt=f"p{i}", code="x", summary=f"s{i}", style="3b1b"
        )
    rows = _list_few_shots_sync(session, limit=2)
    assert len(rows) == 2
