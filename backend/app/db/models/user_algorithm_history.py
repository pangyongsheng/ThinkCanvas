"""ORM model for ``user_algorithm_history`` — 跨会话的算法轨迹。

每个 (user_id, algorithm_name) 一行；同一算法名重复出现时只更新
``seen_count`` / ``last_status`` / ``last_message_id`` 等。

为什么需要：
  * agent 不知道"上次做过冒泡排序" → 用户每次都说"再讲一遍"
  * algorithm_name 由异步 extractor 从对话里抽出（见
    ``app/agents/algorithm_extractor.py``）
  * ``embedding`` 用 JSON 存 embedding vector —— 当前数据量（每个用户几十条）
    用不上 pgvector；Python cosine 计算够用

去重策略：
  * ``UNIQUE(user_id, algorithm_name)`` —— 完全同名合并
  * 写新行前 cosine 相似度 ≥0.85 也合并（避免 "冒泡" 和 "bubble sort" 两行）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


class UserAlgorithmHistory(Base):
    """用户做过的算法轨迹，跨会话去重。"""

    __tablename__ = "user_algorithm_history"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 算法名（小写、归一化后）。extractor 用 LLM 抽成英文短语。
    # 例："bubble sort" / "binary search" / "merge sort"。
    algorithm_name: Mapped[str] = mapped_column(String(100), nullable=False)

    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_conversation_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_message_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Embedding of algorithm_name (bge-small-zh, 512 dims) as JSON text.
    # 用于去重时算相似度（与即将插入的算法名比较），避免 "bubble sort"
    # 和 "冒泡排序" 重复建行。
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        UniqueConstraint(
            "user_id", "algorithm_name", name="uq_user_algorithm",
        ),
        Index("ix_user_algorithm_history_user_updated", "user_id", "updated_at"),
    )


__all__ = ["UserAlgorithmHistory"]
