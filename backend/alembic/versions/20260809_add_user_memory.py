"""add long-term memory tables

Revision ID: 20260809_user_memory
Revises: 20260808_add_trace_id
Create Date: 2026-08-09

新增 3 张表，给 agent 跨会话记忆能力：

  * ``user_preferences``         — 1:1 挂 users，存语言/默认风格/自定义说明
  * ``user_algorithm_history``   — user × algorithm 去重轨迹
  * ``user_feedback``            — 用户对 assistant message 的 👍/👎/✏️

所有 FK 走 ON DELETE CASCADE —— 用户删账号或 message 被删，下游自动清。

``user_algorithm_history`` 上 ``UNIQUE(user_id, algorithm_name)`` 防止同名
重复建行；embedding 字段暂时存 JSON Text（不用 pgvector，等量大了再迁）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_user_memory"
down_revision: Union[str, None] = "20260808_add_trace_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 放宽 alembic_version 字段长度
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    # --- user_preferences (1:1) ---
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.String(length=26),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("default_style", sa.String(length=20), nullable=True),
        sa.Column("extra_instructions", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- user_algorithm_history ---
    op.create_table(
        "user_algorithm_history",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=26),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("algorithm_name", sa.String(length=100), nullable=False),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_status", sa.String(length=10), nullable=True),
        sa.Column(
            "last_conversation_id",
            sa.String(length=26),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_message_id",
            sa.String(length=26),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "algorithm_name", name="uq_user_algorithm",
        ),
    )
    op.create_index(
        "ix_user_algorithm_history_user_updated",
        "user_algorithm_history",
        ["user_id", "updated_at"],
    )

    # --- user_feedback ---
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=26),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(length=26),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_feedback_user_created",
        "user_feedback",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_user_feedback_message",
        "user_feedback",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_feedback_message", table_name="user_feedback")
    op.drop_index("ix_user_feedback_user_created", table_name="user_feedback")
    op.drop_table("user_feedback")

    op.drop_index(
        "ix_user_algorithm_history_user_updated",
        table_name="user_algorithm_history",
    )
    op.drop_table("user_algorithm_history")

    op.drop_table("user_preferences")
