"""``user_algorithm_history`` 表 DAO — 跨会话算法轨迹去重读写。"""
from __future__ import annotations

import json
import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAlgorithmHistory


logger = logging.getLogger("thinkcanvas.agents.dao.user_algorithm_history")


class UserAlgorithmHistoryDAO:
    """``user_algorithm_history`` 表读写。

    关键操作：
      * ``upsert_by_name`` — 严格同名合并（UNIQUE 约束兜底）
      * ``upsert_with_embedding_dedup`` — embedding 相似度合并
      * ``list_recent`` — 拼 system prompt 时拉最近 N 条
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_by_name(
        self,
        *,
        user_id: str,
        algorithm_name: str,
        status: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> UserAlgorithmHistory:
        """``INSERT ... ON CONFLICT DO UPDATE`` —— 同名直接合并计数。

        ``seen_count`` 自增 1，``last_*`` 字段覆盖，``embedding`` 仅在
        首次插入时写入（避免覆盖更早的向量）。
        """
        embedding_json = (
            json.dumps(embedding, ensure_ascii=False) if embedding else None
        )
        stmt = pg_insert(UserAlgorithmHistory).values(
            user_id=user_id,
            algorithm_name=algorithm_name,
            seen_count=1,
            last_status=status,
            last_conversation_id=conversation_id,
            last_message_id=message_id,
            embedding=embedding_json,
        ).on_conflict_do_update(
            constraint="uq_user_algorithm",
            set_={
                "seen_count": UserAlgorithmHistory.__table__.c.seen_count + 1,
                "last_status": status,
                "last_conversation_id": conversation_id,
                "last_message_id": message_id,
                # embedding 不覆盖 —— 首次插入的向量保留
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()
        # 拿回行（refresh）
        return await self._get_by_name(user_id, algorithm_name)

    async def _get_by_name(
        self, user_id: str, algorithm_name: str,
    ) -> UserAlgorithmHistory | None:
        stmt = select(UserAlgorithmHistory).where(
            UserAlgorithmHistory.user_id == user_id,
            UserAlgorithmHistory.algorithm_name == algorithm_name,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_recent(
        self,
        user_id: str,
        *,
        limit: int = 20,
    ) -> list[UserAlgorithmHistory]:
        """读最近 ``limit`` 条按 ``updated_at`` 倒序。

        召回时按"最近活跃优先"，不是按计数排序 —— 最近做过的算法
        放进 prompt 价值最高。
        """
        stmt = (
            select(UserAlgorithmHistory)
            .where(UserAlgorithmHistory.user_id == user_id)
            .order_by(UserAlgorithmHistory.updated_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_all_with_embedding(
        self, user_id: str,
    ) -> list[UserAlgorithmHistory]:
        """只返回带 embedding 的行 —— 供去重相似度计算用。"""
        stmt = (
            select(UserAlgorithmHistory)
            .where(
                UserAlgorithmHistory.user_id == user_id,
                UserAlgorithmHistory.embedding.is_not(None),
            )
        )
        return list((await self.session.execute(stmt)).scalars())

    async def merge_into(
        self,
        *,
        source_id: str,
        target_id: str,
    ) -> None:
        """把 ``source_id`` 那行的计数累加到 ``target_id``，然后删 source。

        用途：extractor 算出"冒泡"和"bubble sort"相似度 >0.85，
        把 source 合并到 target，seen_count 相加，保留 target 的 embedding。
        """
        from sqlalchemy import delete as sa_delete

        source = await self.session.get(UserAlgorithmHistory, source_id)
        target = await self.session.get(UserAlgorithmHistory, target_id)
        if source is None or target is None:
            return
        target.seen_count += source.seen_count
        # 取较新的 last_*
        if (
            source.updated_at
            and (target.updated_at is None or source.updated_at > target.updated_at)
        ):
            target.last_status = source.last_status
            target.last_conversation_id = source.last_conversation_id
            target.last_message_id = source.last_message_id
        await self.session.execute(
            sa_delete(UserAlgorithmHistory).where(
                UserAlgorithmHistory.id == source_id,
            )
        )
        await self.session.commit()


__all__ = ["UserAlgorithmHistoryDAO"]
