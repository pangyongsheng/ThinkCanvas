"""HTTP routes for task history (Step 5: 持久化).

Endpoints
    - GET    /tasks           list recent tasks (most recent first)
    - GET    /tasks/{id}      fetch one task by id
    - DELETE /tasks/{id}      delete one task
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.storage import tasks as task_store

router = APIRouter(tags=["tasks"])


class TaskOut(BaseModel):
    id: str
    prompt: str
    code: str | None
    scene_name: str | None
    video_url: str | None
    status: str
    style: str
    duration_sec: float
    error: str | None
    tool_calls: int
    created_at: str
    updated_at: str


def _to_out(t) -> TaskOut:
    return TaskOut(
        id=t.id,
        prompt=t.prompt,
        code=t.code,
        scene_name=t.scene_name,
        video_url=t.video_url,
        status=t.status,
        style=t.style,
        duration_sec=t.duration_sec,
        error=t.error,
        tool_calls=t.tool_calls,
        created_at=t.created_at.isoformat() if t.created_at else "",
        updated_at=t.updated_at.isoformat() if t.updated_at else "",
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[TaskOut]:
    """Most recent generation tasks (most recent first)."""
    rows = await task_store.list_tasks(session, limit=limit, offset=offset)
    return [_to_out(t) for t in rows]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    t = await task_store.get_task(session, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_out(t)


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    ok = await task_store.delete_task(session, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    return {"deleted": task_id}


__all__ = ["router", "TaskOut"]
