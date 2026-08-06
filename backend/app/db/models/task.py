"""SQLAlchemy ORM model for generation tasks.

A ``Task`` is one user request to generate a Manim video from a prompt.
We persist:

  - the input prompt
  - the generated code (from the agent's structured CodeOutput)
  - the rendered video URL (relative path under /media)
  - the status (pending / succeeded / failed)
  - duration / error for observability
  - timestamps (created/updated)

The ``id`` is a ULID string — sortable by creation time, URL-safe, and
distinct from numeric auto-increment IDs (which collide in distributed
deploys).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


class Task(Base):
    """One generation request and its result."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    style: Mapped[str] = mapped_column(String(20), nullable=False, default="3b1b")
    duration_sec: Mapped[float] = mapped_column(default=0.0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __all__ = ["Task"]
