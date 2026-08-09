"""ORM model for ``user_feedback`` — 用户对生成结果的 👍 / 👎 / ✏️。

一行 = 用户对一条 assistant message 的反馈：
  * ``verdict`` — "liked" / "disliked"
  * ``note``    — 用户写的注释（可选）

作用：
  * 下次会话拼 system prompt 时引用"上次说不好"的算法 → agent 主动换思路
  * 攒够量以后批量 retrain few-shot 库（v2）

设计：
  * ``message_id`` FK ON DELETE CASCADE —— message 删了，feedback 也删
  * 一个 message 可以被多次反馈（用户改主意）；DAO 层 ``upsert`` 覆盖最新 verdict
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


class UserFeedback(Base):
    """用户对 assistant message 的反馈。"""

    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # 拉"这个用户最近给的反馈"时按 user_id + 时间排序
        Index("ix_user_feedback_user_created", "user_id", "created_at"),
        # 反查"这条 message 被谁评价过"
        Index("ix_user_feedback_message", "message_id"),
    )


__all__ = ["UserFeedback"]
