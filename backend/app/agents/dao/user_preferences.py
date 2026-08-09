"""``user_preferences`` 表 DAO — 跨会话偏好读写。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserPreference


logger = logging.getLogger("thinkcanvas.agents.dao.user_preferences")


# 用 sentinel 区分"调用方没传" vs "调用方传了 None 想清空字段"。
# 默认值用 None 区分不出来 — None 本身可能就是合法值（清空某个字段）。
_UNSET: Any = object()


class UserPreferencesDAO:
    """``user_preferences`` 1:1 表的读写。

    所有方法都是按 ``user_id`` 维度工作 —— 不存在跨用户共享偏好的场景。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: str) -> UserPreference | None:
        """读用户偏好；不存在返回 ``None``（调用方按缺省值处理）。"""
        return await self.session.get(UserPreference, user_id)

    async def upsert(
        self,
        *,
        user_id: str,
        language: Any = _UNSET,
        default_style: Any = _UNSET,
        extra_instructions: Any = _UNSET,
    ) -> UserPreference:
        """``get-or-create`` + 字段更新。

        只更新调用方**显式提供**的字段 —— 没传的字段保持原值（不变 None 也不变空）。
        想清空某个字段，传 ``None``：DAO 看见 ``None`` 就会把对应列置空。
        """
        pref = await self.get(user_id)
        if pref is None:
            # 首次写入：未提供的字段保持 None（DB 列也允许 NULL）
            pref = UserPreference(
                user_id=user_id,
                language=language if language is not _UNSET else None,
                default_style=default_style if default_style is not _UNSET else None,
                extra_instructions=(
                    extra_instructions if extra_instructions is not _UNSET else None
                ),
            )
            self.session.add(pref)
        else:
            if language is not _UNSET:
                pref.language = language
            if default_style is not _UNSET:
                pref.default_style = default_style
            if extra_instructions is not _UNSET:
                pref.extra_instructions = extra_instructions
        await self.session.commit()
        await self.session.refresh(pref)
        return pref

    async def reset(self, user_id: str) -> bool:
        """清空偏好（删行，下次 ``get`` 会返回 None）。"""
        pref = await self.get(user_id)
        if pref is None:
            return False
        await self.session.delete(pref)
        await self.session.commit()
        return True


__all__ = ["UserPreferencesDAO"]
