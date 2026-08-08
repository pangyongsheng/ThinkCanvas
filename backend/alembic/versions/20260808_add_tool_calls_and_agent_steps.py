"""add tool_calls to messages + create agent_steps

Revision ID: 20260808_agent_steps
Revises: 20260807_add_few_shot_embedding
Create Date: 2026-08-08

两件事：

1. ``messages.tool_calls INT NULL`` — 每次 assistant 生成 LLM 实际触发了
   几次工具调用（汇总指标）。agent_steps 表存每步明细。

2. 新表 ``agent_steps`` — 每条记录一次 LLM 的工具调用或工具结果，关联到
   ``messages.id``（多轮对话模式）或 ``tasks.id``（单次生成模式），二选一。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260808_agent_steps"
down_revision: Union[str, None] = "20260807_add_few_shot_embedding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("tool_calls", sa.Integer(), nullable=True, server_default="0"),
    )

    # alembic 默认 version_num VARCHAR(32) 装不下新 revision id，先放宽。
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "message_id",
            sa.String(length=26),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            sa.String(length=26),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=20), nullable=False),
        sa.Column("tool_name", sa.String(length=50), nullable=True),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("tool_args", sa.Text(), nullable=True),
        sa.Column("tool_result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_steps_message_id", "agent_steps", ["message_id"])
    op.create_index("ix_agent_steps_task_id", "agent_steps", ["task_id"])
    op.create_index("ix_agent_steps_created_at", "agent_steps", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_steps_created_at", table_name="agent_steps")
    op.drop_index("ix_agent_steps_task_id", table_name="agent_steps")
    op.drop_index("ix_agent_steps_message_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_column("messages", "tool_calls")
