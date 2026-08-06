"""add few_shots.summary_embedding

Revision ID: 20260807_add_few_shot_embedding
Revises: 20260807_add_few_shot_summary
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_add_few_shot_embedding"
down_revision: Union[str, None] = "20260807_add_few_shot_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "few_shots",
        sa.Column("summary_embedding", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("few_shots", "summary_embedding")
