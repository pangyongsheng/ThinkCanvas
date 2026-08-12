"""ORM model for a multi-turn conversation.

A ``Conversation`` groups a stream of user→assistant messages around a
single visual topic. The conversation holds style + a denormalised title
for fast sidebar rendering; messages are split into their own table.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.models.message import Message
from app.db.models.user import ANON_USER_ID
from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


class Conversation(Base):
    """A threaded, multi-turn generation session."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    style: Mapped[str] = mapped_column(String(20), nullable=False, default="3b1b")
    version: Mapped[int] = mapped_column(default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        default=ANON_USER_ID,
        server_default=ANON_USER_ID,
    )

    # P3 阶段控制 — "scripting" / "coding" / "done"
    #   scripting — Script Designer 在跑，等用户确认脚本
    #   coding   — 用户已确认（或简单任务跳过），Coder 跑
    #   done     — 最终代码已生成
    phase: Mapped[str] = mapped_column(
        String(16), nullable=False, default="coding", server_default="coding",
    )
    # P3 当前脚本（每轮 Script Designer 更新），None 表示还没出
    current_script: Mapped[Optional[dict]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True,
    )

    __table_args__ = (
        Index("ix_conversations_updated_at", "updated_at"),
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_phase", "phase"),
    )

    __all__ = ["Conversation"]


__all__ = ["Conversation"]
