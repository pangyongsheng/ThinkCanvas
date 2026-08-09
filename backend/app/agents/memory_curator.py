"""MemoryCurator — LLM 分析原始事件，输出对 memories 的 patch。

每次新事件到来：
  1. 拿用户的 active memories
  2. 把事件 + memories 给 LLM，让它决定 add / reinforce / update / remove
  3. 应用 patch

设计取舍：
  * **Curator 不是必须成功** — LLM 失败时只丢一条记忆，不影响主流程
  * **Patch 用 JSON 输出** — 严格 schema，parse 失败就静默放弃（不污染 DB）
  * **不要 backfill 老数据** — 一次性 LLM 调用成本已经够高，只处理新事件

事件类型（``EventKind``）：
  * ``generation``  — agent 跑完一次生成（含 prompt + code + status）
  * ``feedback``    — 用户给了 👍/👎
  * ``preference``  — 用户改了偏好
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dao.user_memories import UserMemoriesDAO
from app.agents.summarizer import _extract_text_from_message
from app.db.models import CATEGORIES, UserMemory
from app.llm.client import get_llm


logger = logging.getLogger("thinkcanvas.agents.memory_curator")


EventKind = Literal["generation", "feedback", "preference"]


@dataclass(slots=True)
class MemoryEvent:
    """触发 curator 分析的原始事件。"""
    kind: EventKind
    summary: str  # 1~3 句话描述事件（curator 看这个）
    extra: dict[str, Any]  # kind-specific 额外字段


# ---------------------------------------------------------------------------
# LLM system prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "你是一个用户记忆 curator。维护关于某个用户的洞察清单。"
    "原始事件（用户做了什么）会传给你，你需要决定是否产生 / 强化 / 更新 / 删除洞察。\n\n"
    "洞察分类 category：\n"
    "  - preference  — 稳定偏好（语言 / 输出长度 / 风格倾向）\n"
    "  - pattern     — 行为模式（习惯 refine、偏好某种题材、反馈频率）\n"
    "  - avoidance   — 应该避免的事（动画太长、配色太暗、节奏太慢）\n"
    "  - style_hint  — 视觉 / 代码风格提示（喜欢高对比 / 函数式代码 / 简洁 prompt）\n\n"
    "输出严格的 JSON（不要解释，不要 markdown fence）：\n"
    '{"actions": [\n'
    '  {"type": "add", "category": "<one of the 4>", "insight": "<一句话 ≤80 字>", "confidence": <0.0~1.0>, "evidence_count": <int ≥ 1>},\n'
    '  {"type": "reinforce", "memory_id": "<id>", "reason": "<一句话为什么这个事件支持它>"},\n'
    '  {"type": "update", "memory_id": "<id>", "new_insight": "<一句话>", "new_category": "<optional>"},\n'
    '  {"type": "remove", "memory_id": "<id>", "reason": "<为什么这个洞察不再成立>"}\n'
    "]}\n\n"
    "规则：\n"
    "1. **质量 > 数量** — 不确定时输出空 actions 数组\n"
    "2. **不要重复** — 现有 memory 已经覆盖这个洞察时，用 reinforce 而不是 add\n"
    "3. **不要过度具体** — '做过冒泡排序' 太具体；'基础排序已熟练' 是洞察\n"
    "4. **不要过度抽象** — '喜欢数学' 没信息量；'偏好快速动画（≤5s）' 是洞察\n"
    "5. **reward / punish 反馈** 几乎总能产生 avoidance 类洞察\n"
    "6. confidence 起始 0.5；强化事件明显支持时 0.7；高度确信 0.9"
)


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------

class MemoryCurator:
    """调 LLM 分析事件，patch memories 表。

    所有方法都是 fire-and-forget 友好 —— 抛异常只 log，不向外传。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.dao = UserMemoriesDAO(session)

    async def process(self, event: MemoryEvent, *, user_id: str) -> int:
        """处理一个事件。返回实际应用的 action 数（用于监控）。

        失败路径（LLM 抛 / JSON parse 失败）只 log，不抛。
        """
        memories = await self.dao.list_all_active(user_id)
        if not memories and event.kind in ("feedback", "preference"):
            # 第一次反馈 / 改偏好，没有历史记忆 —— 仍然值得分析
            pass

        actions = await self._ask_llm(event, memories)
        if not actions:
            logger.info("memory_curator.no_actions user=%s kind=%s",
                       user_id, event.kind)
            return 0

        applied = await self._apply(actions, user_id)
        logger.info(
            "memory_curator.applied user=%s kind=%s actions=%d of=%d",
            user_id, event.kind, applied, len(actions),
        )
        return applied

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------

    async def _ask_llm(
        self,
        event: MemoryEvent,
        memories: list[UserMemory],
    ) -> list[dict]:
        """调 LLM 返回 actions 列表；任何异常返回 []。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        mem_text = self._format_memories(memories)
        user_msg = (
            f"## 新事件（kind={event.kind}）\n{event.summary}\n\n"
            f"## extra\n{json.dumps(event.extra, ensure_ascii=False)}\n\n"
            f"## 当前 memories\n{mem_text or '(无)'}"
        )

        try:
            llm = get_llm()
            result = await llm.ainvoke(
                [SystemMessage(content=_SYSTEM), HumanMessage(content=user_msg)]
            )
            text = _extract_text_from_message(getattr(result, "content", None))
            return self._parse_actions(text)
        except Exception:
            logger.exception("memory_curator.llm_failed kind=%s", event.kind)
            return []

    @staticmethod
    def _format_memories(memories: list[UserMemory]) -> str:
        """memories → 列表字符串，给 LLM 看。"""
        if not memories:
            return ""
        lines: list[str] = []
        for m in memories:
            lines.append(
                f"- id={m.id} category={m.category} "
                f"confidence={m.confidence:.2f} evidence={m.evidence_count}\n"
                f"  insight: {m.insight}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_actions(payload: str) -> list[dict]:
        """严格 JSON parse。失败 / schema 不对都返回 []。"""
        if not payload:
            return []
        payload = payload.strip()
        # 兼容 ```json ... ``` fence
        if payload.startswith("```"):
            payload = payload.strip("`").strip()
            if payload.startswith("json"):
                payload = payload[4:].strip()
        try:
            obj = json.loads(payload)
        except ValueError:
            logger.warning("memory_curator.parse_failed payload=%r", payload[:200])
            return []
        actions = obj.get("actions")
        if not isinstance(actions, list):
            return []
        # 简单校验 + 过滤未知 type
        valid: list[dict] = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            t = a.get("type")
            if t in ("add", "reinforce", "update", "remove"):
                valid.append(a)
        return valid

    # ------------------------------------------------------------------
    # Apply patch
    # ------------------------------------------------------------------

    async def _apply(self, actions: list[dict], user_id: str) -> int:
        """把 actions 应用到 DB。"""
        n = 0
        for a in actions:
            t = a.get("type")
            try:
                if t == "add":
                    cat = a.get("category", "pattern")
                    if cat not in CATEGORIES:
                        cat = "pattern"
                    await self.dao.add(
                        user_id=user_id,
                        category=cat,
                        insight=a.get("insight", "").strip()[:200],
                        confidence=float(a.get("confidence", 0.5)),
                        evidence_count=int(a.get("evidence_count", 1)),
                    )
                    n += 1
                elif t == "reinforce":
                    mid = a.get("memory_id")
                    if mid:
                        result = await self.dao.reinforce(mid)
                        if result is not None:
                            n += 1
                elif t == "update":
                    mid = a.get("memory_id")
                    new_insight = a.get("new_insight", "").strip()
                    if mid and new_insight:
                        result = await self.dao.update_insight(
                            memory_id=mid,
                            new_insight=new_insight[:200],
                            new_category=a.get("new_category"),
                        )
                        if result is not None:
                            n += 1
                elif t == "remove":
                    mid = a.get("memory_id")
                    if mid:
                        if await self.dao.remove(mid):
                            n += 1
            except Exception:
                logger.exception(
                    "memory_curator.action_failed type=%s action=%r",
                    t, a,
                )
        return n


__all__ = ["MemoryCurator", "MemoryEvent"]
