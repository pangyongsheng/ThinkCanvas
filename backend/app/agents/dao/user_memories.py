"""``user_memories`` 表 DAO — LLM 提炼后的用户洞察读写。

``MemoryCurator`` 是唯一写入方（生成 add / reinforce / update / remove patch）。
``build_memory_block`` 是唯一读取方（拼到 system prompt）。

设计要点：
  * active 行通过 ``status='active' AND superseded_by_id IS NULL`` 过滤
  * 召回时按 confidence × recency 排序（不是简单 updated_at DESC）
"""
from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserMemory


logger = logging.getLogger("thinkcanvas.agents.dao.user_memories")


class UserMemoriesDAO:
    """``user_memories`` 表读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(
        self,
        user_id: str,
        *,
        limit: int = 20,
    ) -> list[UserMemory]:
        """拉所有 active 行，按 confidence × recency 倒序。

        排序：先 confidence DESC，再 last_reinforced_at DESC。
        limit 硬上限是 prompt 大小，调用方传。
        """
        stmt = (
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.superseded_by_id.is_(None),
            )
            .order_by(
                UserMemory.confidence.desc(),
                UserMemory.last_reinforced_at.desc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_all_active(self, user_id: str) -> list[UserMemory]:
        """不设 limit — 给 MemoryCurator 看全量用。"""
        stmt = (
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.superseded_by_id.is_(None),
            )
            .order_by(UserMemory.confidence.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def add(
        self,
        *,
        user_id: str,
        category: str,
        insight: str,
        confidence: float = 0.5,
        evidence_count: int = 1,
    ) -> UserMemory:
        """curator 输出 'add' 时调。"""
        mem = UserMemory(
            user_id=user_id,
            category=category,
            insight=insight,
            confidence=confidence,
            evidence_count=evidence_count,
            status="active",
        )
        self.session.add(mem)
        await self.session.commit()
        await self.session.refresh(mem)
        return mem

    async def reinforce(self, memory_id: str) -> UserMemory | None:
        """curator 输出 'reinforce' 时调。

        evidence_count +1，confidence 提升（封顶 1.0）。
        """
        mem = await self.session.get(UserMemory, memory_id)
        if mem is None:
            return None
        mem.evidence_count = mem.evidence_count + 1
        # 每次 reinforce +0.05，封顶 1.0
        mem.confidence = min(1.0, mem.confidence + 0.05)
        await self.session.commit()
        await self.session.refresh(mem)
        return mem

    async def update_insight(
        self,
        *,
        memory_id: str,
        new_insight: str,
        new_category: str | None = None,
    ) -> UserMemory | None:
        """curator 输出 'update' 时调 —— 改写文案。

        实现：建一条新 memory（带原 evidence_count），把旧的 superseded_by_id 指向新行。
        这样历史可审计，旧行不会被直接修改。
        """
        old = await self.session.get(UserMemory, memory_id)
        if old is None:
            return None

        new = UserMemory(
            user_id=old.user_id,
            category=new_category or old.category,
            insight=new_insight,
            confidence=old.confidence,
            evidence_count=old.evidence_count,
            status="active",
            superseded_by_id=None,
        )
        self.session.add(new)
        await self.session.flush()  # 让 new 拿到 id
        old.superseded_by_id = new.id
        old.status = "superseded"
        await self.session.commit()
        await self.session.refresh(new)
        return new

    async def remove(self, memory_id: str) -> bool:
        """curator 输出 'remove' 时调 —— 标 status='decayed'，保留行。

        不真删，方便审计。
        """
        mem = await self.session.get(UserMemory, memory_id)
        if mem is None:
            return False
        mem.status = "decayed"
        await self.session.commit()
        return True


__all__ = ["UserMemoriesDAO"]
