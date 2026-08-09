"""``user_feedback`` 表 DAO — 用户 👍 / 👎 反馈写入。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, User, UserFeedback


logger = logging.getLogger("thinkcanvas.agents.dao.user_feedback")


class UserFeedbackDAO:
    """``user_feedback`` 写入 + 最近反馈召回。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        *,
        user_id: str,
        message_id: str,
        verdict: str,
        note: str | None = None,
    ) -> UserFeedback:
        """新增一条反馈。

        同 ``message_id`` 可以有多个 verdict（用户改主意）—— 历史都保留，
        但召回时只看最近一条。
        """
        fb = UserFeedback(
            user_id=user_id,
            message_id=message_id,
            verdict=verdict,
            note=note,
        )
        self.session.add(fb)
        await self.session.commit()
        await self.session.refresh(fb)
        return fb

    async def list_recent(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> list[UserFeedback]:
        """最近 ``limit`` 条反馈（按时间）。"""
        stmt = (
            select(UserFeedback)
            .where(UserFeedback.user_id == user_id)
            .order_by(UserFeedback.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_latest_for_message(
        self, message_id: str,
    ) -> UserFeedback | None:
        """拿某条 message 的最新一条反馈（用于 UI 显示 👍/👎 状态）。"""
        stmt = (
            select(UserFeedback)
            .where(UserFeedback.message_id == message_id)
            .order_by(UserFeedback.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


__all__ = ["UserFeedbackDAO"]
