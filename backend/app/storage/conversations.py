"""Async CRUD layer for ``Conversation`` and ``Message`` rows.

Conversations group user→assistant exchanges around a single topic. Only
the most recent assistant message keeps non-null ``code`` / ``video_url``
(we never want to leak stale media into the UI); older assistant rows
remain in place for chronological display but with those columns cleared.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Message


def _truncate_title(text: str, limit: int = 20) -> str:
    """First non-empty line, trimmed, max ``limit`` chars."""
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:limit]
    return text.strip()[:limit]


async def create_conversation(
    session: AsyncSession,
    *,
    prompt: str,
    style: str = "3b1b",
) -> Conversation:
    """Insert a new conversation + its first user message in one shot."""
    conv = Conversation(
        title=_truncate_title(prompt),
        style=style,
    )
    session.add(conv)
    await session.flush()  # get conv.id without committing yet
    msg = Message(
        conversation_id=conv.id,
        role="user",
        content=prompt.strip(),
    )
    session.add(msg)
    await session.commit()
    await session.refresh(conv)
    return conv


async def get_conversation(
    session: AsyncSession, conversation_id: str
) -> Optional[Conversation]:
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_conversations(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """Most recent conversations first, with light metadata only."""
    stmt = (
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def append_user_message(
    session: AsyncSession,
    conversation_id: str,
    content: str,
) -> Optional[Message]:
    msg = Message(conversation_id=conversation_id, role="user", content=content.strip())
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def write_assistant_message(
    session: AsyncSession,
    conversation_id: str,
    *,
    status: str,
    content: str,
    code: Optional[str] = None,
    video_url: Optional[str] = None,
    scene_name: Optional[str] = None,
    duration_sec: Optional[float] = None,
    error: Optional[str] = None,
) -> Optional[Message]:
    """Insert the assistant's latest turn.

    Clears ``code``/``video_url`` on any prior assistant row for this
    conversation so the *only* place those values live is the newest
    one — keeps the UI from accidentally rendering stale media.
    """
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.role == "assistant",
    )
    prior_rows = list((await session.execute(stmt)).scalars())
    for row in prior_rows:
        row.code = None
        row.video_url = None
        row.duration_sec = None
        row.scene_name = None

    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        status=status,
        content=content,
        code=code,
        video_url=video_url,
        scene_name=scene_name,
        duration_sec=duration_sec,
        error=error,
    )
    session.add(msg)

    # Bump conversation.version + updated_at so the sidebar reorders.
    conv = await session.get(Conversation, conversation_id)
    if conv is not None:
        conv.version = (conv.version or 0) + 1
        conv.updated_at = datetime.now(UTC)
        if not conv.title:
            # Backfill title from the new user message if empty.
            # (caller has usually set it on create; this is a safety net.)
            pass

    await session.commit()
    await session.refresh(msg)
    return msg


async def delete_conversation(
    session: AsyncSession, conversation_id: str
) -> bool:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        return False
    await session.delete(conv)
    await session.commit()
    return True


__all__ = [
    "create_conversation",
    "get_conversation",
    "list_conversations",
    "append_user_message",
    "write_assistant_message",
    "delete_conversation",
]
