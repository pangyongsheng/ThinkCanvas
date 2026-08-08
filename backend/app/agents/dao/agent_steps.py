"""Agent 执行轨迹的 DAO。

``agent_steps`` 表记录每次 agent 跑的工具调用和返回结果，按 ``message_id`` 外键
关联到 ``messages`` 表。Middleware 是唯一调用方，路由层禁止直接接触。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStep


logger = logging.getLogger("thinkcanvas.agents.dao.agent_steps")


def _serialize_tool_args(value: Any) -> str | None:
    """dict / list / str / None → 落库字符串。

    ``agent_steps.tool_args`` 列是 Text（不存 JSONB），所以 dict 必须序列化。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class AgentStepsDAO:
    """``agent_steps`` 表的写入封装。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write_steps(
        self,
        *,
        message_id: str,
        steps: list[dict],
    ) -> int:
        """批量插入 agent 执行步骤。

        ``steps`` 元素格式（来自 middleware ``wrap_tool_call`` hook）：
            ``step_type / tool_name / tool_call_id / tool_args /
            tool_result / error / step_index``

        返回插入行数。空列表返回 0，不报错。
        """
        if not steps:
            return 0
        rows = [
            AgentStep(
                message_id=message_id,
                step_index=int(s.get("step_index", 0)),
                step_type=str(s.get("step_type", "unknown"))[:20],
                tool_name=s.get("tool_name"),
                tool_call_id=s.get("tool_call_id"),
                tool_args=_serialize_tool_args(s.get("tool_args")),
                tool_result=s.get("tool_result"),
                error=s.get("error"),
            )
            for s in steps
        ]
        self.session.add_all(rows)
        await self.session.flush()
        logger.info(
            "agent_steps.write message=%s rows=%d",
            message_id, len(rows),
        )
        return len(rows)


__all__ = ["AgentStepsDAO"]
