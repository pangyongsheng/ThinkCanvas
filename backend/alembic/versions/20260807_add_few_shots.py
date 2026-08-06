"""add few_shots table

Revision ID: 20260807_add_few_shots
Revises: 20260806_add_users
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_add_few_shots"
down_revision: Union[str, None] = "20260806_add_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "few_shots",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("style", sa.String(length=20), nullable=False),
        sa.Column(
            "source_conversation_id",
            sa.String(length=26),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_message_id", sa.String(length=26), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_few_shots_style", "few_shots", ["style"])
    op.create_index("ix_few_shots_created_at", "few_shots", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_few_shots_created_at", table_name="few_shots")
    op.drop_index("ix_few_shots_style", table_name="few_shots")
    op.drop_table("few_shots")
