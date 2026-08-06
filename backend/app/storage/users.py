"""Storage helpers for the (anonymous) User table.

Auth model is intentionally trivial: no passwords, no sessions. Identity
is a ULID the browser keeps in localStorage and sends as the
``X-User-Id`` header. Server-side we just upsert rows on every request
so we can attribute conversations and (later) preferences.
"""
from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ANON_USER_ID, User


async def upsert_user(session: AsyncSession, user_id: str) -> User:
    """Insert a new User row, or refresh ``last_seen_at`` on the existing one.

    Returns the row (existing or freshly inserted). Never raises — an
    unknown ULID just becomes a new anonymous user.
    """
    existing = await session.get(User, user_id)
    if existing is not None:
        existing.last_seen_at = datetime.now(UTC)
        await session.commit()
        return existing

    user = User(id=user_id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def touch_last_seen(session: AsyncSession, user_id: str) -> None:
    """Lightweight ``last_seen_at`` bump, used by the request middleware.

    Skips the upsert overhead: if the row doesn't exist yet, we let the
    explicit ``upsert_user`` call (from conversation creation or the
    frontend's first POST) handle it. A 404 here just means "we don't
    know this user yet" — that's fine.
    """
    user = await session.get(User, user_id)
    if user is None:
        return
    user.last_seen_at = datetime.now(UTC)
    await session.commit()


async def get_or_create_anonymous(session: AsyncSession) -> User:
    """Return the hard-coded anon user, creating it if missing.

    Used as the fallback identity when a request comes in without an
    ``X-User-Id`` header (e.g. curl probes, pre-migration traffic).
    """
    return await upsert_user(session, ANON_USER_ID)


__all__ = ["upsert_user", "touch_last_seen", "get_or_create_anonymous"]
