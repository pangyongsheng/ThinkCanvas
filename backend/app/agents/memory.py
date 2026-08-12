"""长期记忆召回 + 拼装成 system prompt 片段。

v2 升级 — 不再读原始事件表（user_algorithm_history / user_feedback /
user_preferences），只读 ``user_memories``（LLM 提炼后的洞察）。

调用方：
  * ``AgentService.run_initial / run_refine`` 在 ``_run_agent`` 之前
    调 ``build_memory_block`` 拿到一段字符串，再塞给 ``builder.build_agent``
    的 ``extra_system_prompt`` 后面。

为什么只读 ``user_memories``：
  * 原始事件由 ``MemoryCurator`` 异步提炼后才入 ``user_memories``
  * ``user_memories`` 是 insight 形式，已经过滤噪声 / 合并重复 / 抽象层级
  * 拼到 prompt 的只有精炼后的洞察，不污染 LLM 上下文

输出形态：一段 markdown 文本，直接拼在 system prompt 末尾。
空数据时返回空字符串。
"""
from __future__ import annotations

import logging

from app.agents.dao.user_memories import UserMemoriesDAO
from app.db.models import UserMemory
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("thinkcanvas.agents.memory")


# 召回上限 —— system prompt 上下文宝贵，硬限制
MAX_MEMORIES_IN_PROMPT = 15


async def build_memory_block(
    session: AsyncSession,
    *,
    user_id: str,
) -> str:
    """召回 user_id 的 active memories，拼成可塞进 system prompt 的 markdown 段。

    任何异常都不报错 —— 调用方拿到空字符串即可。
    """
    try:
        memories = await UserMemoriesDAO(session).list_active(
            user_id, limit=MAX_MEMORIES_IN_PROMPT,
        )
    except Exception:
        # SELECT 失败会让 session 进入 failed transaction 状态，
        # 调用方（_run_agent）后续还要用同一个 session 写 messages，
        # 必须 rollback 把 session 救回来，否则下一次 commit 会炸
        # asyncpg.exceptions.InFailedSQLTransactionError。
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("memory.rollback_failed user=%s", user_id)
        logger.exception("memory.read_failed user=%s", user_id)
        return ""

    block = _render_memories(memories)
    if block:
        logger.info(
            "memory.built user=%s count=%d bytes=%d",
            user_id, len(memories), len(block),
        )
    return block


def _render_memories(memories: list[UserMemory]) -> str:
    """memories → markdown 段（按 category 分组）。"""
    if not memories:
        return ""

    # 按 category 分组 — 让 LLM 一次看清同类
    groups: dict[str, list[UserMemory]] = {}
    for m in memories:
        groups.setdefault(m.category, []).append(m)

    sections: list[str] = []
    category_labels = {
        "preference":  "用户偏好",
        "pattern":     "用户行为模式",
        "avoidance":   "应避免的事",
        "style_hint":  "风格提示",
    }
    for cat in ("preference", "pattern", "avoidance", "style_hint"):
        rows = groups.get(cat)
        if not rows:
            continue
        lines = [f"- {m.insight}" for m in rows]
        sections.append(f"## {category_labels[cat]}\n" + "\n".join(lines))

    if not sections:
        return ""
    return "\n\n".join(sections)


__all__ = ["build_memory_block", "MAX_MEMORIES_IN_PROMPT"]
