"""add users table + conversations.user_id

Revision ID: 20260806_add_users
Revises: 20260806_xxxxxx
Create Date: 2026-08-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_add_users"
down_revision: Union[str, None] = "20260806_xxxxxx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Single hard-coded owner for all pre-existing conversations. Identifiable
# by its lex prefix so it's obvious in logs / DB dumps.
ANON_USER_ID = "01ANON00000000000000000000"


def upgrade() -> None:
    # 1. Create users table.
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("default_style", sa.String(length=20), nullable=True),
    )

    # 2. Seed the anonymous user so the FK backfill has a target.
    op.execute(
        sa.text(
            "INSERT INTO users (id) VALUES (:uid) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(uid=ANON_USER_ID)
    )

    # 3. Add user_id column to conversations as nullable first.
    op.add_column(
        "conversations",
        sa.Column(
            "user_id",
            sa.String(length=26),
            nullable=True,
        ),
    )

    # 4. Backfill existing rows.
    op.execute(
        sa.text("UPDATE conversations SET user_id = :uid WHERE user_id IS NULL").bindparams(
            uid=ANON_USER_ID
        )
    )

    # 5. Tighten to NOT NULL + add FK + index.
    op.alter_column(
        "conversations",
        "user_id",
        existing_type=sa.String(length=26),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_conversations_user_id",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conversations_user_id",
        "conversations",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_constraint("fk_conversations_user_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "user_id")
    op.drop_table("users")
