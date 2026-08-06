"""ORM model for an anonymous user (cookie-ULID based).

Authentication model is intentionally trivial: there is no password /
email / login flow. Identity is a ULID stored in the browser's
``localStorage`` and sent back as the ``X-User-Id`` header. The first
time the server sees a new ULID it upserts a row here. Rows are never
deleted — even "anonymous" usage is logged so conversations can be
re-attributed across browser sessions.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.session import Base


def _new_ulid() -> str:
    return str(ULID())


# A single hard-coded ULID used as the owner of any pre-existing
# conversation created before the user system existed (i.e. the data
# already in the DB when this migration runs). Identifiable as "anon"
# by its lex prefix.
ANON_USER_ID = "01ANON00000000000000000000"


class User(Base):
    """An anonymous, identity-less user.

    Has no PII — just a ULID and a few timestamps / preferences.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_new_ulid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    default_style: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __all__ = ["User"]


__all__ = ["User", "ANON_USER_ID"]
