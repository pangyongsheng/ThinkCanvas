"""LangChain AgentMiddleware：自动捕获 agent 工具调用 + 落库 + SSE 推送。

设计要点：

* **唯一入口**：所有走 ``build_agent`` 构造的 agent 都自动挂这个中间件，
  不需要每个路由单独接 on_event 回调，杜绝漏写埋点。
* **零硬编码 SQL**：本文件不出现 SQLAlchemy 表达式，所有写入都走 ``AgentStepsDAO``
  / ``MessagesDAO``。中间件只做"业务数据组装 + DAO 调用"的转运角色。
* **跨调用隔离**：每次 ``ainvoke`` 之前在 ``abefore_agent`` 重置实例状态，
  避免并发请求间数据污染（FastAPI 单进程下是顺序的，但写法上仍守一道）。

``runtime.context`` 约定（routes 通过 ``agent.ainvoke(..., context=...)`` 传入）：

  * ``conversation_id`` — 必填，messages / agent_steps 外键目标
  * ``on_event`` — 可选，``Callable[[str, dict], Awaitable[None]] | None``，
    用于 SSE 流式推送 step 事件
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.dao.agent_steps import AgentStepsDAO
from app.agents.dao.messages import MessagesDAO


logger = logging.getLogger("thinkcanvas.agents.middleware.persistence")

# ``awrap_tool_call`` / ``aafter_agent`` 公共类型别名
OnEvent = Callable[[str, dict], Awaitable[None]] | None
# 与基类 ``AgentMiddleware.awrap_tool_call`` 签名完全一致 — 基类声明
# ``Awaitable[ToolMessage | Command[Any]]``，本类不外扩能力只调 handler。
ToolCallHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]

_SCENE_NAME_RE = re.compile(r"class\s+(\w+)\s*\(\s*Scene\s*\)")


def _extract_scene_name(code: str | None) -> str | None:
    """从 ``from manim import *`` 后的代码中抽出第一个 ``class Foo(Scene)``。"""
    if not code:
        return None
    m = _SCENE_NAME_RE.search(code)
    return m.group(1) if m else None


class AgentPersistenceMiddleware(AgentMiddleware):
    """统一捕获 agent 执行轨迹、自动落库、可选 SSE 推送。

    ``AgentStepsDAO`` / ``MessagesDAO`` 由调用方注入，中间件自己不持有 session。
    """

    def __init__(
        self,
        *,
        dao_steps: AgentStepsDAO,
        dao_messages: MessagesDAO,
    ) -> None:
        self.dao_steps = dao_steps
        self.dao_messages = dao_messages
        # per-run 状态（每次 abefore_agent 重置）
        self._steps: list[dict] = []
        self._message_id: str | None = None
        self._on_event: OnEvent = None
        self._step_counter: int = 0

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """预创建 assistant 消息壳 + 重置本轮 state。"""
        ctx: dict = runtime.context or {}
        conversation_id = ctx.get("conversation_id")
        if not conversation_id:
            raise ValueError(
                "AgentPersistenceMiddleware.before_agent: "
                "runtime.context['conversation_id'] is required, "
                f"got runtime.context={ctx!r}"
            )

        msg = await self.dao_messages.create_assistant_shell(
            conversation_id=conversation_id,
        )
        self._message_id = msg.id
        self._steps = []
        self._step_counter = 0
        self._on_event = ctx.get("on_event")

        logger.info(
            "agent_middleware.before_agent conversation=%s message=%s",
            conversation_id, msg.id,
        )
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: ToolCallHandler,
    ) -> ToolMessage | Command[Any]:
        """捕获每次工具调用 + 落库到 ``agent_steps``。

        LangChain ``awrap_tool_call`` 钩子只给 ``request`` 和 ``handler``，
        不给 ``runtime``——所以 ``on_event`` / ``message_id`` 必须在
        ``abefore_agent`` 时存到实例上，本方法里直接读 self。
        """
        tc = request.tool_call
        if isinstance(tc, dict):
            tool_name = tc.get("name")
            tool_call_id = tc.get("id")
            tool_args = tc.get("args")
        else:
            tool_name = getattr(tc, "name", None)
            tool_call_id = getattr(tc, "id", None)
            tool_args = getattr(tc, "args", None)

        step: dict[str, Any] = {
            "step_index": self._step_counter,
            "step_type": "tool_call",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_args": tool_args,
        }
        self._steps.append(step)
        self._step_counter += 1

        if self._on_event is not None:
            await self._on_event("tool_call", {"tool": tool_name})

        # 真正执行工具
        result: ToolMessage | Command[Any] = await handler(request)

        # 中间件本身不产生 Command — 但 handler 可能；只关心
        # ToolMessage 的 status / content。
        if not isinstance(result, ToolMessage):
            return result
        is_error = getattr(result, "status", None) == "error"
        result_text = str(getattr(result, "content", ""))[:4000]
        self._steps[-1]["tool_result"] = result_text
        if is_error:
            self._steps[-1]["error"] = result_text

        if self._on_event is not None:
            await self._on_event("tool_result", {
                "tool": tool_name,
                "status": "failed" if is_error else "ok",
                "error": self._steps[-1].get("error"),
            })

        return result

    async def aafter_agent(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """agent 跑完：批量落 agent_steps + 更新 assistant 消息的 code/status。"""
        if self._message_id is None:
            return None

        if self._steps:
            await self.dao_steps.write_steps(
                message_id=self._message_id,
                steps=self._steps,
            )

        # 从 state 拿 structured_response（create_agent 的 response_format 输出）
        structured = state.get("structured_response") if hasattr(state, "get") else None
        code = getattr(structured, "code", None) if structured else None
        status = "ok" if code else "failed"

        await self.dao_messages.finalize_after_agent(
            message_id=self._message_id,
            code=code,
            scene_name=_extract_scene_name(code),
            status=status,
        )

        logger.info(
            "agent_middleware.after_agent message=%s status=%s code_len=%d",
            self._message_id, status, len(code) if code else 0,
        )

        # 重置实例状态，让下一次 ainvoke 不污染
        self._steps = []
        self._message_id = None
        self._on_event = None
        self._step_counter = 0
        return None


__all__ = ["AgentPersistenceMiddleware"]
