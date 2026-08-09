"""ORM model for ``user_preferences`` — 跨会话的用户偏好。

一对一挂 ``users.id``：
  * ``language``         — 通信语言（"zh" / "en"）
  * ``default_style``    — 默认视觉风格（覆盖前端下拉框）
  * ``extra_instructions`` — 用户写死的偏好文本（"做的都是算法题，输出要短"）
  * ``updated_at``       — 最近一次改写时间

设计取舍：
  * 用 1-1 表而不是塞进 ``users`` —— users 是身份信息，不想每次更新偏好都
    触碰 users 表行（避免并发 last_seen_at 写竞争）
  * ``extra_instructions`` 用 TEXT 而不是 JSONB —— 用户写的是自由文本，
    直接当 system prompt 片段用最简单
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


class UserPreference(Base):
    """用户跨会话偏好。"""

    __tablename__ = "user_preferences"

    # 一对一：user_id 是 PK
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    default_style: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extra_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = ["UserPreference"]
