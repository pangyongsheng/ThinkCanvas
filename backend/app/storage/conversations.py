"""Async CRUD layer for ``Conversation`` and ``Message`` rows.

Conversations group user→assistant exchanges around a single topic. Only
the most recent assistant message keeps non-null ``code`` / ``video_url``
(we never want to leak stale media into the UI); older assistant rows
remain in place for chronological display but with those columns cleared.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import project_root
from app.db.models import AgentStep, Conversation, Message


logger = logging.getLogger("thinkcanvas.storage.conversations")

# Static /media is mounted at project_root/media. ``video_url`` stored in
# messages is "http://localhost:8000/media/<rel>" (see api.v1.render.to_video_url).
# Strip the scheme+host prefix to recover the relative path, then resolve it
# under MEDIA_ROOT.
MEDIA_ROOT = project_root / "media"
_MEDIA_URL_PREFIXES = (
    "http://localhost:8000/media/",
    "http://127.0.0.1:8000/media/",
)


def _truncate_title(text: str, limit: int = 20) -> str:
    """First non-empty line, trimmed, max ``limit`` chars."""
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:limit]
    return text.strip()[:limit]


def _video_url_to_path(video_url: str) -> Path | None:
    """Resolve a stored video_url back to an absolute file path.

    Returns ``None`` if the URL is in an unexpected shape so the caller
    can skip it without raising — a missing file is not a delete-failure.
    """
    for prefix in _MEDIA_URL_PREFIXES:
        if video_url.startswith(prefix):
            rel = video_url[len(prefix):]
            return (MEDIA_ROOT / rel).resolve()
    # Already-relative URLs (e.g. "/media/foo/bar.mp4") — used by some tests.
    if video_url.startswith("/media/"):
        return (MEDIA_ROOT / video_url[len("/media/"):]).resolve()
    return None


def _delete_video_files(video_urls: list[str]) -> int:
    """Best-effort delete of video files referenced by ``video_url`` strings.

    Returns the count of files actually deleted. Missing / malformed
    URLs are silently skipped — the conversation row's gone anyway,
    the file's residue on disk is a soft cost we accept.
    """
    deleted = 0
    for url in video_urls:
        if not url:
            continue
        path = _video_url_to_path(url)
        if path is None or not path.is_file():
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("delete_video_files.skip path=%s err=%s", path, exc)
    return deleted


async def create_conversation(
    session: AsyncSession,
    *,
    prompt: str,
    style: str = "3b1b",
    user_id: str,
) -> Conversation:
    """Insert a new conversation + its first user message in one shot.

    ``user_id`` is mandatory — every conversation has an owner so the
    sidebar / history endpoints can scope to "this user only".
    """
    conv = Conversation(
        title=_truncate_title(prompt),
        style=style,
        user_id=user_id,
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
    session: AsyncSession,
    conversation_id: str,
    *,
    user_id: str | None = None,
) -> Optional[Conversation]:
    """Fetch a conversation, optionally scoped to its owner.

    ``user_id=None`` is allowed (admin / cross-user debugging paths); the
    HTTP layer should always pass the request's user_id.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_conversations(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
) -> list[Conversation]:
    """Most recent conversations first, optionally scoped to one user.

    ``user_id=None`` returns everything (admin / diagnostics). The HTTP
    sidebar should pass the request's user_id.
    """
    stmt = (
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# Cap how many recent user messages we feed to the LLM as "history".
# 6 is enough for progressive refinement ("make it red" -> "also bigger"
# -> "add a label") without bloating the prompt on long sessions.
USER_HISTORY_LIMIT = 6


def _list_user_messages_sync(
    session,
    conversation_id: str,
    limit: int = USER_HISTORY_LIMIT,
) -> list[str]:
    """Sync core — same query as the async wrapper below.

    Kept sync so unit tests can hit it with a plain ``Session`` without
    needing an async driver.
    """
    stmt = (
        select(Message.content)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        # ``created_at`` is the primary order, but two rows inserted in
        # the same DB clock-tick (common in SQLite tests, and possible
        # under load in Postgres too) tie — fall back to ULID lex order
        # so the sort is deterministic.
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list(session.execute(stmt).scalars().all())
    rows.reverse()  # chronological for the prompt
    return [c for c in rows if c]


async def list_user_messages(
    session: AsyncSession,
    conversation_id: str,
    limit: int = USER_HISTORY_LIMIT,
) -> list[str]:
    """Return the most recent user message contents in chronological order.

    Capped at ``USER_HISTORY_LIMIT`` (default 6) — long conversations
    shouldn't dump the entire request history into the refine prompt.
    Old rounds beyond the cap are dropped.

    Used by the refine handler to give the LLM a textual history of what
    the user has been asking for, so it can understand progressive
    instructions ("same thing but red" / "also add a label") even though
    we only feed the latest assistant code.
    """
    stmt = (
        select(Message.content)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    return [content for content in rows if content]


def _append_user_message_sync(session, conversation_id: str, content: str) -> Message:
    """Sync core — same logic as the async wrapper, for unit tests."""
    msg = Message(
        conversation_id=conversation_id,
        role="user",
        content=content.strip(),
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


async def append_user_message(
    session: AsyncSession,
    conversation_id: str,
    content: str,
) -> Message:
    msg = Message(conversation_id=conversation_id, role="user", content=content.strip())
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


def _write_assistant_message_sync(
    session,
    conversation_id: str,
    *,
    status: str,
    content: str,
    code: Optional[str] = None,
    video_url: Optional[str] = None,
    scene_name: Optional[str] = None,
    duration_sec: Optional[float] = None,
    error: Optional[str] = None,
    tool_calls: Optional[int] = None,
) -> Message:
    """Sync core — see ``write_assistant_message`` for full docstring."""
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.role == "assistant",
    )
    prior_rows = list(session.execute(stmt).scalars())
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
        tool_calls=tool_calls,
    )
    session.add(msg)

    conv = session.get(Conversation, conversation_id)
    if conv is not None:
        conv.version = (conv.version or 0) + 1
        conv.updated_at = datetime.now(UTC)

    session.commit()
    session.refresh(msg)
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
    tool_calls: Optional[int] = None,
) -> Message:
    """Insert the assistant's latest turn.

    Clears ``code``/``video_url`` on any prior assistant row for this
    conversation so the *only* place those values live is the newest
    one — keeps the UI from accidentally rendering stale media.

    ``tool_calls`` — 这次生成 LLM 实际触发的工具调用总次数（汇总指标）。
    明细见 ``write_agent_steps`` 落 agent_steps 表。
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
        tool_calls=tool_calls,
    )
    session.add(msg)

    # Bump conversation.version + updated_at so the sidebar reorders.
    conv = await session.get(Conversation, conversation_id)
    if conv is not None:
        conv.version = (conv.version or 0) + 1
        conv.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(msg)
    return msg


async def delete_conversation(
    session: AsyncSession,
    conversation_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    """Delete a conversation (and its messages via cascade).

    Best-effort also deletes the on-disk video file referenced by the
    *current* assistant row's ``video_url`` — only one assistant row
    keeps a non-null ``video_url`` at any time (see
    ``write_assistant_message``), so that's the only file the
    conversation owns. Old assistant rows already have ``video_url=NULL``
    (cleared on each new write), so they don't add to the cleanup set.

    ``user_id`` scopes the delete: a non-owner asking to delete gets
    ``False`` (treated as 404 by the HTTP layer). ``user_id=None``
    deletes unconditionally (admin path).
    """
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        return False
    if user_id is not None and conv.user_id != user_id:
        return False

    # Snapshot video_urls BEFORE the cascade wipe — once the session
    # deletes the conversation, conv.messages is lazy-loaded onto a
    # session that's about to be invalidated.
    video_urls = [
        m.video_url for m in conv.messages
        if m.role == "assistant" and m.video_url
    ]

    await session.delete(conv)
    await session.commit()

    if video_urls:
        n = _delete_video_files(video_urls)
        if n:
            logger.info(
                "delete_conversation.purged_files conv=%s files=%d",
                conversation_id, n,
            )
    return True


__all__ = [
    "create_conversation",
    "get_conversation",
    "list_conversations",
    "append_user_message",
    "list_user_messages",
    "USER_HISTORY_LIMIT",
    "_list_user_messages_sync",
    "_append_user_message_sync",
    "_write_assistant_message_sync",
    "write_assistant_message",
    "delete_conversation",
]





def _serialize_tool_args(value) -> str | None:
    """dict / list / None → JSON 字符串（落 agent_steps.tool_args 用）。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


async def write_agent_steps(
    session: AsyncSession,
    *,
    message_id: str | None = None,
    task_id: str | None = None,
    steps: list[dict],
) -> int:
    """批量插入 agent 执行步骤。

    ``steps`` 元素格式（来自 ``agent_recovery.extract_from_result`` 的
    ``tool_steps`` 字段）：
        ``step_index / step_type / tool_name / tool_call_id / tool_args /
        tool_result / error``

    返回插入行数。
    """
    if not steps:
        return 0
    rows = [
        AgentStep(
            message_id=message_id,
            task_id=task_id,
            step_index=int(s.get("step_index", 0)),
            step_type=str(s.get("step_type", "unknown"))[:20],
            tool_name=s.get("tool_name"),
            tool_call_id=s.get("tool_call_id"),
            # tool_args 列是 Text/JSONB-friendly 字符串 — dict 必须先序列化。
            # （原 agent_recovery 里 _truncate_dict 返回 dict，需要 json.dumps）
            tool_args=_serialize_tool_args(s.get("tool_args")),
            tool_result=s.get("tool_result"),
            error=s.get("error"),
        )
        for s in steps
    ]
    session.add_all(rows)
    await session.flush()
    return len(rows)
