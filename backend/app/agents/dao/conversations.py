"""``conversations`` 表的 DAO — 创建 / 读 / 删 / 列。

职责：只管理 ``conversations`` 表本身的行；不直接写 user / assistant 消息，
由 ``MessagesDAO`` / ``AgentPersistenceMiddleware`` 各司其职。这样三层边界
非常清晰：

  * ``ConversationsDAO``     — 会话生命周期的 CRUD + 关联读
  * ``MessagesDAO``          — messages 表写入
  * ``AgentPersistenceMiddleware`` — agent 跑起来后自动落库
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import project_root
from app.db.models import Conversation


logger = logging.getLogger("thinkcanvas.agents.dao.conversations")

# ``/media`` 静态目录根。``video_url`` 形如 ``http://localhost:8000/media/<rel>``，
# 反向解析回绝对路径用于清理文件用。
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
    """Resolve a stored ``video_url`` back to an absolute file path.

    Returns ``None`` if the URL is in an unexpected shape so the caller
    can skip it without raising.
    """
    for prefix in _MEDIA_URL_PREFIXES:
        if video_url.startswith(prefix):
            rel = video_url[len(prefix):]
            return (MEDIA_ROOT / rel).resolve()
    if video_url.startswith("/media/"):
        return (MEDIA_ROOT / video_url[len("/media/"):]).resolve()
    return None


class ConversationsDAO:
    """``conversations`` 表 CRUD + 关联读操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        prompt: str,
        style: str,
        user_id: str,
    ) -> Conversation:
        """Insert a new conversation row.

        ``user_id`` is mandatory — every conversation has an owner so the
        sidebar / history endpoints can scope to "this user only".

        注意：本方法只建会话本身，不写 user / assistant 消息。
        ``MessagesDAO.append_user_message`` 负责追加 user 消息；
        assistant 消息由 ``AgentPersistenceMiddleware.before_agent`` 创建。
        """
        conv = Conversation(
            title=_truncate_title(prompt),
            style=style,
            user_id=user_id,
        )
        self.session.add(conv)
        await self.session.flush()  # get conv.id without committing yet
        await self.session.commit()
        await self.session.refresh(conv)
        return conv

    async def set_phase(
        self,
        conversation_id: str,
        phase: str,
    ) -> None:
        """单独更新 conversation.phase（不改其他字段）。"""
        conv = await self.session.get(Conversation, conversation_id)
        if conv is None:
            return None
        conv.phase = phase
        await self.session.commit()
        await self.session.refresh(conv)

    async def update_after_run(
        self,
        *,
        conversation_id: str,
        phase: str | None = None,
        current_script: dict | None = None,
    ) -> None:
        """跑完一次 supervisor 后更新 phase + current_script。"""
        conv = await self.session.get(Conversation, conversation_id)
        if conv is None:
            return None
        if phase is not None:
            conv.phase = phase
        if current_script is not None:
            conv.current_script = current_script
        await self.session.commit()
        await self.session.refresh(conv)

    async def get(
        self,
        conversation_id: str,
        *,
        user_id: str | None = None,
    ) -> Conversation | None:
        """Fetch a conversation, optionally scoped to its owner.

        ``user_id=None`` is allowed (admin / cross-user debugging paths);
        HTTP layer should always pass the request's user_id.
        """
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """List conversations belonging to a user, newest first.

        Sorted by ``updated_at`` (sidebar reorder signal) with
        ``created_at`` as tie-breaker.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def delete(
        self,
        conversation_id: str,
        *,
        user_id: str | None = None,
    ) -> bool:
        """Delete a conversation (cascade messages) + its on-disk video file.

        Best-effort video cleanup. ``user_id`` scopes the delete: a non-owner
        asking to delete gets ``False`` (treated as 404 by HTTP layer).

        实现要点：
          * 用 SELECT + selectinload 一次性把 messages 拉回来 — 避免后续
            cascade 时再触发 lazy load（async context + greenlet 边界上
            可能踩到 ``MissingGreenlet``）
          * snapshot 视频 URL 后，**用 bulk DELETE** 直接按 conversation_id
            删 messages + 让 DB CASCADE 删 agent_steps；不再走 ORM 级联
            删除路径，少一层 ORM 状态机出错点
          * 先删 messages 再删 conversation — DB FK 双向 CASCADE 都到位，
            任意一边都能兜底
        """
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        r = await self.session.execute(stmt)
        conv = r.scalar_one_or_none()
        if conv is None:
            return False
        if user_id is not None and conv.user_id != user_id:
            return False

        # Snapshot video_urls BEFORE wipe — 需要 messages 数据
        video_urls = [
            m.video_url for m in conv.messages
            if m.role == "assistant" and m.video_url
        ]

        # Bulk delete messages（DB 层 agent_steps.message_id ON DELETE CASCADE
        # 会自动把 agent_steps 也带走）。conversation 这边等 messages 删完
        # 再删，避免 ORM 级联 + DB 级联双重删除时顺序歧义。
        from app.db.models import Message
        await self.session.execute(
            sa_delete(Message).where(Message.conversation_id == conversation_id)
        )
        await self.session.execute(
            sa_delete(Conversation).where(Conversation.id == conversation_id)
        )
        await self.session.commit()

        if video_urls:
            n = _delete_video_files(video_urls)
            if n:
                logger.info(
                    "conversations.delete.purged_files conv=%s files=%d",
                    conversation_id, n,
                )
        return True

    async def list_user_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 6,
    ) -> list[str]:
        """Return most recent user message contents in chronological order.

        Capped at ``limit`` (default 6) — long conversations shouldn't dump
        the entire request history into the refine prompt.
        """
        from app.db.models import Message

        stmt = (
            select(Message.content)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        rows.reverse()
        return [c for c in rows if c]


# ---------------------------------------------------------------------------
# helpers（不在 DAO 类里，因为涉及文件 IO）
# ---------------------------------------------------------------------------


def _delete_video_files(video_urls: list[str]) -> int:
    """Best-effort delete of video files referenced by ``video_url`` strings."""
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


__all__ = ["ConversationsDAO", "MEDIA_ROOT"]
