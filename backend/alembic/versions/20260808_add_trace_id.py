"""add trace_id to messages + agent_steps

Revision ID: 20260808_add_trace_id
Revises: 20260808_agent_steps
Create Date: 2026-08-08

LangSmith 集成：每次 agent 跑会拿到顶层 trace_id（LangChain run_id），
存到 messages 和 agent_steps 上，没开 LangSmith 时为 NULL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260808_add_trace_id"
down_revision: Union[str, None] = "20260808_agent_steps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("trace_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_steps",
        sa.Column("trace_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "trace_id")
    op.drop_column("messages", "trace_id")
