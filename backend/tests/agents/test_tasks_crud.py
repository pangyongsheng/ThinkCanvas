"""CRUD tests for the tasks storage layer.

Uses a stub AsyncSession that records calls and returns canned ORM-like
objects, so we don't need a live DB or aiosqlite during unit tests.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.storage import tasks as store


def _make_task_row(**overrides) -> MagicMock:
    """Build a fake Task ORM row."""
    row = MagicMock()
    row.id = overrides.get("id", "01ARZ3NDEKTSV4RRFFQ69G5FAV")
    row.prompt = overrides.get("prompt", "")
    row.code = overrides.get("code")
    row.scene_name = overrides.get("scene_name")
    row.video_url = overrides.get("video_url")
    row.status = overrides.get("status", "pending")
    row.duration_sec = overrides.get("duration_sec", 0.0)
    row.error = overrides.get("error")
    row.tool_calls = overrides.get("tool_calls", 0)
    row.created_at = overrides.get("created_at", datetime(2026, 8, 6, 12, 0, 0))
    row.updated_at = overrides.get("updated_at", datetime(2026, 8, 6, 12, 0, 0))
    return row


class _FakeSession:
    """Minimal AsyncSession stand-in for the CRUD layer."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self._by_id: dict[str, MagicMock] = {}

    def add(self, obj: Any) -> None:
        # Mimic SQLAlchemy: assigning the PK after add (autoincrement or default)
        if not obj.id:
            obj.id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        self.added.append(obj)

    async def get(self, _model: Any, pk: str) -> Optional[MagicMock]:
        return self._by_id.get(pk)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self._by_id.pop(getattr(obj, "id", None), None)

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        if obj not in self._by_id.values():
            self._by_id[getattr(obj, "id", None)] = obj

    async def execute(self, _stmt: Any) -> Any:
        rows = list(self._by_id.values())
        # Reverse-sort by created_at (mirrors order_by(Task.created_at.desc()))
        rows.sort(key=lambda r: r.created_at, reverse=True)
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result


@pytest.mark.asyncio
async def test_create_task_assigns_id_and_status():
    s = _FakeSession()
    t = await store.create_task(s, prompt="冒泡排序")
    assert s.added == [t]
    assert t.id
    assert t.prompt == "冒泡排序"
    assert t.status == "pending"


@pytest.mark.asyncio
async def test_get_task_returns_row():
    s = _FakeSession()
    t = _make_task_row(prompt="二分查找")
    s._by_id[t.id] = t
    fetched = await store.get_task(s, t.id)
    assert fetched is t


@pytest.mark.asyncio
async def test_get_task_missing_returns_none():
    s = _FakeSession()
    assert await store.get_task(s, "missing-id") is None


@pytest.mark.asyncio
async def test_list_tasks_orders_newest_first():
    s = _FakeSession()
    a = _make_task_row(id="01ARZ3NDEKTSV4RRFFQ69G5FAV", prompt="a",
                       created_at=datetime(2026, 8, 6, 9))
    b = _make_task_row(id="01ARZ3NDEKTSV4RRFFQ69G5FAW", prompt="b",
                       created_at=datetime(2026, 8, 6, 10))
    c = _make_task_row(id="01ARZ3NDEKTSV4RRFFQ69G5FAX", prompt="c",
                       created_at=datetime(2026, 8, 6, 11))
    s._by_id = {a.id: a, b.id: b, c.id: c}
    rows = await store.list_tasks(s)
    assert [r.prompt for r in rows] == ["c", "b", "a"]


@pytest.mark.asyncio
async def test_update_task_partial_only_sets_passed_fields():
    s = _FakeSession()
    t = _make_task_row(prompt="test")
    s._by_id[t.id] = t

    updated = await store.update_task(
        s,
        t.id,
        status="succeeded",
        code="from manim import *",
        video_url="/media/x.mp4",
        duration_sec=12.3,
        tool_calls=2,
    )
    assert updated is t
    assert t.status == "succeeded"
    assert t.code == "from manim import *"
    assert t.video_url == "/media/x.mp4"
    assert t.duration_sec == 12.3
    assert t.tool_calls == 2
    # untouched fields stay as defaults
    assert t.scene_name is None
    assert t.error is None


@pytest.mark.asyncio
async def test_update_task_missing_returns_none():
    s = _FakeSession()
    assert await store.update_task(s, "missing", status="x") is None


@pytest.mark.asyncio
async def test_delete_task_removes_row():
    s = _FakeSession()
    t = _make_task_row(prompt="to delete")
    s._by_id[t.id] = t
    assert await store.delete_task(s, t.id) is True
    assert await store.get_task(s, t.id) is None


@pytest.mark.asyncio
async def test_delete_task_missing_returns_false():
    s = _FakeSession()
    assert await store.delete_task(s, "missing") is False
