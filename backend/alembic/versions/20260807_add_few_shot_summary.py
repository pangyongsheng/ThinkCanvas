"""add few_shots.summary

Revision ID: 20260807_add_few_shot_summary
Revises: 20260807_add_few_shots
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_add_few_shot_summary"
down_revision: Union[str, None] = "20260807_add_few_shots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOT NULL with a server-side default so existing rows (from the
    # earlier migration) get a placeholder instead of failing the column
    # add. The HTTP layer fills this in for all new rows.
    op.add_column(
        "few_shots",
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    # Drop the server default now that existing rows are populated;
    # new rows must always provide a non-empty summary.
    op.alter_column("few_shots", "summary", server_default=None)


def downgrade() -> None:
    op.drop_column("few_shots", "summary")
