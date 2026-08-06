"""ORM model for a multi-turn conversation.

A ``Conversation`` groups a stream of user→assistant messages around a
single visual topic. The conversation holds style + a denormalised title
for fast sidebar rendering; messages are split into their own table.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.models.message import Message
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

    __table_args__ = (
        Index("ix_conversations_updated_at", "updated_at"),
    )

    __all__ = ["Conversation"]


__all__ = ["Conversation"]
