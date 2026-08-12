"""P3 confirm handler 必须渲染 + attach_video，否则前端半小时看不到视频。"""
from __future__ import annotations

from pathlib import Path


CONFIRM_SRC = Path("app/api/v1/conversations.py").read_text()


def _slice_confirm() -> str:
    """从 confirm_conversation 函数定义到下一个 @router 装饰器之间的源码。"""
    start = CONFIRM_SRC.index("async def confirm_conversation(")
    rest = CONFIRM_SRC[start:]
    end = rest.find("\n@router")
    return rest[:end] if end > 0 else rest


def test_confirm_calls_render_code():
    """回归保护：confirm handler 必须调 render_code。

    之前漏了 — 前端 confirm 后半小时看不到视频，video_url 一直是 null。
    """
    body = _slice_confirm()
    assert "render_code(" in body, (
        "confirm_conversation 没调 render_code — 前端会卡在「视频还没渲染好」"
    )


def test_confirm_calls_attach_video():
    """回归保护：confirm handler 渲染成功后必须 attach_video。"""
    body = _slice_confirm()
    assert "attach_video(" in body, (
        "confirm_conversation 没调 attach_video — DB 里 video_url 永远是 null"
    )


def test_confirm_returns_video_url():
    """回归保护：响应里必须有 video_url，前端才能直接拿到。"""
    body = _slice_confirm()
    assert '"video_url"' in body, (
        "confirm 响应缺 video_url — 前端还要再 getConversation 一次"
    )


def test_confirm_marks_render_failed_on_error():
    """渲染失败时要把错误写进 assistant 消息（不是只抛 500）。"""
    body = _slice_confirm()
    assert "mark_render_failed" in body, (
        "confirm 没在渲染失败时 mark_render_failed — 错误状态丢失"
    )
