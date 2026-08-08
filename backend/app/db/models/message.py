"""ORM model for messages inside a conversation.

A ``Message`` is either a user utterance or the assistant's structured
response for that turn:

  - user       → ``content`` only
  - assistant  → ``content`` (human-readable summary like "✅ 完成 · 2.1s"),
                 plus ``code`` and ``video_url`` for the *latest* turn.

History rule: only the most recent assistant message in a conversation
keeps non-null ``code`` / ``video_url``. Earlier assistant rows are
left in place for chronological display, with ``code``/``video_url``
cleared once a newer revision lands.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


class Message(Base):
    """One turn in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    conversation_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Assistant-only fields; nullable so user rows can ignore them.
    code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    scene_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 这次生成 LLM 实际调了几次工具（汇总指标）。agent_steps 表存每步明细。
    tool_calls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")  # noqa: F821

    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
    )

    __all__ = ["Message"]


__all__ = ["Message"]
