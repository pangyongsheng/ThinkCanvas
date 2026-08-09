"""ORM model for ``user_memories`` — LLM 提炼后的用户洞察。

不是「原始事件存储」，是「agent 关于这个用户知道什么」。
每次发生新事件（生成完成、用户反馈、偏好修改），``MemoryCurator``
用 LLM 读事件 + 现有 memories，输出 add / reinforce / update / remove patch。

与原始事件表（user_algorithm_history / user_feedback）的关系：
  * 原始事件是 **input**（给 curator 看）
  * user_memories 是 **output**（被 prompt 读）

字段含义：
  * ``category``        — preference / pattern / avoidance / style_hint
  * ``insight``         — 一句话洞察（≤ 200 字）
  * ``confidence``      — 0~1，多次 reinforce 后升高
  * ``evidence_count``  — 多少事件支持这个洞察
  * ``superseded_by_id`` — 被新洞察覆盖时，旧行的指针（保留历史方便审计）
  * ``status``          — 'active' / 'decayed'
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


# 枚举常量 — service / API 引用同一份
CATEGORIES: tuple[str, ...] = (
    "preference",   # 稳定偏好（语言 / 风格 / 输出长度）
    "pattern",      # 行为模式（习惯 refine 多次 / 偏好某种题材）
    "avoidance",    # 应该避免的事（动画太长 / 配色太暗）
    "style_hint",   # 视觉 / 代码风格提示（喜欢高对比 / 函数式代码）
)


class UserMemory(Base):
    """LLM 提炼后的用户洞察。"""

    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    insight: Mapped[str] = mapped_column(Text, nullable=False)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 当一条新 memory 替代这条时，旧行的 superseded_by_id 指向新行
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("user_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_reinforced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # 召回时按用户 + 状态 + 信心倒序
        Index(
            "ix_user_memories_user_status_conf",
            "user_id", "status", "confidence",
        ),
        Index(
            "ix_user_memories_user_reinforced",
            "user_id", "last_reinforced_at",
        ),
    )


__all__ = ["UserMemory", "CATEGORIES"]
