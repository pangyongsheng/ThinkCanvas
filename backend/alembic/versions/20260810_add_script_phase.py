"""add script phase + current_script to conversations / messages — P3 入口分流

Revision ID: 20260810_p3_phase
Revises: 20260809_user_memories
Create Date: 2026-08-10

P3 引入两阶段会话：

  1. ``scripting`` — Script Designer 先出脚本给人确认
  2. ``coding``   — 用户确认后 / 简单任务直接走 Coder → Reviewer

字段：

  conversations.phase        — VARCHAR(16) DEFAULT 'coding'，NOT NULL
  conversations.current_script — JSONB，存最新版脚本（每轮 Script Designer 更新）
  messages.phase             — VARCHAR(16) DEFAULT 'coding'，标记消息属于哪个阶段

不建外键、不强约束 phase 取值，应用层负责只写 ``scripting`` / ``coding`` / ``done``。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_p3_phase"
down_revision: Union[str, None] = "20260809_user_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("phase", sa.String(16), nullable=False, server_default="coding"),
    )
    op.add_column(
        "conversations",
        sa.Column("current_script", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("phase", sa.String(16), nullable=False, server_default="coding"),
    )
    op.create_index(
        "ix_conversations_phase", "conversations", ["phase"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_phase", table_name="conversations")
    op.drop_column("messages", "phase")
    op.drop_column("conversations", "current_script")
    op.drop_column("conversations", "phase")
