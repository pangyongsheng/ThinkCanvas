"""ORM model for agent step trace.

每次 agent 跑（多轮对话或单次生成）的每一步都落一行：

  - ``tool_call``  — AIMessage.tool_calls 触发的工具调用
  - ``tool_result`` — ToolMessage 返回的结果（与上一条 tool_call 通过 tool_call_id 配对）

关联到 ``messages.id``（多轮对话模式）或 ``tasks.id``（单次生成模式），二选一，
两个 FK 都 nullable，靠应用层保证至少一个非空。

为什么必须存：之前只有 messages.error 存最终错误，看不出"LLM 到底调没调工具"、
"调了什么、参数是什么、结果是什么"。失败排查全靠脑补。落库后能直接 SQL 查询：
    SELECT step_index, step_type, tool_name, error
    FROM agent_steps WHERE message_id = '...'
    ORDER BY step_index;
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
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


class AgentStep(Base):
    """One step in an agent's execution trace."""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    message_id: Mapped[Optional[str]] = mapped_column(
        String(26),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        String(26),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_args: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_steps_message_id", "message_id"),
        Index("ix_agent_steps_task_id", "task_id"),
        Index("ix_agent_steps_created_at", "created_at"),
    )

    __all__ = ["AgentStep"]


__all__ = ["AgentStep"]
