"""add style to tasks

Revision ID: 20260806_095254
Revises: 20260806_091159
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_095254"
down_revision: Union[str, None] = "20260806_091159"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "style",
            sa.String(length=20),
            nullable=False,
            server_default="3b1b",
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "style")
