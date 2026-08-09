"""add user_memories — LLM-curated long-term memory

Revision ID: 20260809_user_memories
Revises: 20260809_add_user_memory
Create Date: 2026-08-09

新表 ``user_memories`` — agent 关于这个用户知道什么。
不再直接拼算法历史 / 反馈原文到 prompt；而是 LLM 提炼后的洞察。

每条 memory 一行：
  * category: preference / pattern / avoidance / style_hint
  * insight: 一句话洞察
  * confidence / evidence_count: 信心 + 几次事件支持
  * superseded_by_id: 被新洞察覆盖时的指针（保留历史）
  * status: active / decayed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_user_memories"
down_revision: Union[str, None] = "20260809_add_user_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=26),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("insight", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
        sa.Column(
            "evidence_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "superseded_by_id",
            sa.String(length=26),
            sa.ForeignKey("user_memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=10),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_reinforced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_memories_user_status_conf",
        "user_memories",
        ["user_id", "status", "confidence"],
    )
    op.create_index(
        "ix_user_memories_user_reinforced",
        "user_memories",
        ["user_id", "last_reinforced_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_memories_user_reinforced", table_name="user_memories")
    op.drop_index("ix_user_memories_user_status_conf", table_name="user_memories")
    op.drop_table("user_memories")
