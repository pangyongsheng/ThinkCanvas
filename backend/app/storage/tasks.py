"""Async CRUD layer for ``Task`` rows.

All endpoints that need to read or write tasks go through these helpers.
Keeping the SQL out of the HTTP layer keeps route code thin and lets us
unit-test the data layer in isolation.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task


async def create_task(
    session: AsyncSession,
    *,
    prompt: str,
    status: str = "pending",
    style: str = "3b1b",
) -> Task:
    """Insert a new task row. Returns the persisted instance."""
    task = Task(prompt=prompt, status=status, style=style)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: str) -> Optional[Task]:
    return await session.get(Task, task_id)


async def list_tasks(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    """Most recent tasks first."""
    stmt = (
        select(Task)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_task(
    session: AsyncSession,
    task_id: str,
    *,
    status: Optional[str] = None,
    style: Optional[str] = None,
    code: Optional[str] = None,
    scene_name: Optional[str] = None,
    video_url: Optional[str] = None,
    duration_sec: Optional[float] = None,
    error: Optional[str] = None,
    tool_calls: Optional[int] = None,
    clear_error: bool = False,
) -> Optional[Task]:
    """Partial update — only the fields that are explicitly passed."""
    task = await session.get(Task, task_id)
    if task is None:
        return None

    fields = {
        "status": status,
        "style": style,
        "code": code,
        "scene_name": scene_name,
        "video_url": video_url,
        "duration_sec": duration_sec,
        "error": error,
        "tool_calls": tool_calls,
    }
    for name, value in fields.items():
        if value is not None:
            setattr(task, name, value)
    if clear_error:
        task.error = None
    task.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task_id: str) -> bool:
    task = await session.get(Task, task_id)
    if task is None:
        return False
    await session.delete(task)
    await session.commit()
    return True


__all__ = [
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "delete_task",
]
