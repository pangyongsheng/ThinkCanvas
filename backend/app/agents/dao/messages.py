"""``messages`` 表的 DAO — Agent 执行过程中所有 message 读写都在这里。

注意：路由层在用户视角的"列表 / 详情"读操作可走另一处（ConversationsDAO）；
本文件聚焦 Agent 写入路径（创建助手消息壳、提交代码、附 video_url 等）。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message


logger = logging.getLogger("thinkcanvas.agents.dao.messages")


class MessagesDAO:
    """``messages`` 表写入封装（user 追加 + assistant 各阶段状态更新）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append_user_message(
        self,
        *,
        conversation_id: str,
        content: str,
    ) -> Message:
        """追加一条 user 消息。"""
        msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=content.strip(),
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def create_assistant_shell(
        self,
        *,
        conversation_id: str,
    ) -> Message:
        """在 agent 跑之前预创建 assistant 消息壳，状态 ``generating``。

        让中间件 ``wrap_tool_call`` / ``after_agent`` 拿着这个 id 写 agent_steps
        和最终 code。
        """
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            status="generating",
            content="生成中…",
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def finalize_after_agent(
        self,
        *,
        message_id: str,
        code: str | None,
        scene_name: str | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> Message | None:
        """``after_agent`` 钩子调：写入 code + status + scene_name。

        行为：
          * ``code`` 非空 → ``status="ok"``，并清掉同会话其它 assistant 行的
            code/video_url/scene_name（"最新一份有内容"语义）。
          * ``code`` 为空 → ``status="failed"``，**保留**历史成功行的产物
            ——用户上一轮成功的 code 还在，下一轮 refine 才能基于它继续调整。
        """
        msg = await self.session.get(Message, message_id)
        if msg is None:
            return None
        if code:
            # 成功：清掉旧 assistant 行的产物（保持"最新一份有内容"的语义）
            stmt = select(Message).where(
                Message.conversation_id == msg.conversation_id,
                Message.role == "assistant",
                Message.id != message_id,
            )
            for row in (await self.session.execute(stmt)).scalars():
                row.code = None
                row.video_url = None
                row.duration_sec = None
                row.scene_name = None
        msg.code = code
        msg.scene_name = scene_name
        msg.status = status if code else "failed"
        if error:
            msg.error = error
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def attach_video(
        self,
        *,
        message_id: str,
        video_url: str,
        duration_sec: float | None,
    ) -> Message | None:
        """渲染成功后，把 video_url 写回 assistant 消息。"""
        msg = await self.session.get(Message, message_id)
        if msg is None:
            return None
        msg.video_url = video_url
        if duration_sec is not None:
            msg.duration_sec = duration_sec
        msg.status = "ok"
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def mark_failed(
        self,
        *,
        message_id: str,
        status: str,
        content: str,
        error: str | None = None,
        code: str | None = None,
        scene_name: str | None = None,
    ) -> Message | None:
        """统一失败标记入口（agent 失败 / 渲染失败 / 内部错误共用）。"""
        msg = await self.session.get(Message, message_id)
        if msg is None:
            return None
        msg.status = status
        msg.content = content
        if error is not None:
            msg.error = error
        if code is not None:
            msg.code = code
        if scene_name is not None:
            msg.scene_name = scene_name
        await self.session.commit()
        await self.session.refresh(msg)
        return msg


__all__ = ["MessagesDAO"]
