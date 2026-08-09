"""AgentService — 路由层调用的唯一 agent 业务编排器。

职责：
  1. 把 session 注入 DAO 们
  2. 调用 ``build_agent`` 构造 agent（已挂 AgentPersistenceMiddleware）
  3. 调 ``agent.ainvoke`` 跑 agent——``AgentPersistenceMiddleware`` 自动捕获
     + 落 agent_steps + 更新 assistant 消息
  4. 把渲染（Manim subprocess）委派给路由层；渲染完成后再调 ``MessagesDAO.attach_video``
     把 video_url 写回 assistant 消息

路由层只做 HTTP 接收 / 鉴权 / 调用 service / 渲染 / 返回。
DB 写入全部走 DAO，不再散落在路由里。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Sequence

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.algorithm_extractor import extract_algorithm_name
from app.agents.builder import build_agent
from app.agents.dao.agent_steps import AgentStepsDAO
from app.agents.dao.conversations import ConversationsDAO
from app.agents.dao.messages import MessagesDAO
from app.agents.memory import build_memory_block
from app.agents.memory_curator import MemoryCurator, MemoryEvent
from app.agents.middleware.persistence import AgentPersistenceMiddleware
from app.db.models import Conversation, FewShot, Message


logger = logging.getLogger("thinkcanvas.agents.service")

OnEvent = Callable[[str, dict], Awaitable[None]] | None


@dataclass(slots=True)
class AgentRunResult:
    """Service 跑一次 agent 后的返回值 — 路由层拿到这个再渲染 + 回填。"""
    conversation: Conversation
    user_message: Message
    assistant_message: Message
    code: str | None
    scene_name: str | None
    error: str | None = None


def _require_message(
    label: str,
    msg: Message | None,
    conversation_id: str,
) -> Message:
    """``abefore_agent`` 一定会建 assistant shell，run 完之后一定能拿到。"""
    if msg is None:
        raise RuntimeError(
            f"AgentService: no assistant message after {label} "
            f"(conversation={conversation_id})"
        )
    return msg


class AgentService:
    """编排：建会话 / 跑 agent / 附 video_url。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.dao_conv = ConversationsDAO(session)
        self.dao_msg = MessagesDAO(session)
        self.dao_steps = AgentStepsDAO(session)

    # ------------------------------------------------------------------
    # 首次生成
    # ------------------------------------------------------------------

    async def run_initial(
        self,
        *,
        user_id: str,
        prompt: str,
        style: str,
        few_shots: Sequence[FewShot] = (),
        on_event: OnEvent = None,
    ) -> AgentRunResult:
        """建会话 + user 消息 → 跑 agent → middleware 自动落库。"""
        conv = await self.dao_conv.create(
            prompt=prompt, style=style, user_id=user_id,
        )
        user_msg = await self.dao_msg.append_user_message(
            conversation_id=conv.id, content=prompt,
        )
        assistant_msg = await self._run_agent(
            style=style,
            few_shots=few_shots,
            on_event=on_event,
            prompt_text=prompt.strip(),
            user_id=user_id,
            conversation_id=conv.id,
            label="agent.run_initial",
        )
        assistant = _require_message("run_initial", assistant_msg, conv.id)
        return AgentRunResult(
            conversation=conv,
            user_message=user_msg,
            assistant_message=assistant,
            code=assistant.code,
            scene_name=assistant.scene_name,
        )

    # ------------------------------------------------------------------
    # 多轮调整
    # ------------------------------------------------------------------

    async def run_refine(
        self,
        *,
        conversation_id: str,
        user_id: str,
        instruction: str,
        prev_code: str,
        user_history: list[str],
        style: str,
        few_shots: Sequence[FewShot] = (),
        on_event: OnEvent = None,
    ) -> AgentRunResult:
        """追加 user 消息 → 跑 refine agent → middleware 自动落库。"""
        user_msg = await self.dao_msg.append_user_message(
            conversation_id=conversation_id, content=instruction,
        )
        prompt_text = _build_refine_prompt(prev_code, instruction, user_history)
        assistant_msg = await self._run_agent(
            style=style,
            few_shots=few_shots,
            on_event=on_event,
            prompt_text=prompt_text,
            user_id=user_id,
            conversation_id=conversation_id,
            extra_system_prompt=_REFINE_PREAMBLE,
            label="agent.run_refine",
        )
        conv = await self.dao_conv.get(conversation_id, user_id=user_id)
        if conv is None:
            raise RuntimeError(
                f"AgentService: conversation disappeared mid-refine "
                f"(conversation={conversation_id}, user={user_id})"
            )
        assistant = _require_message("run_refine", assistant_msg, conversation_id)
        return AgentRunResult(
            conversation=conv,
            user_message=user_msg,
            assistant_message=assistant,
            code=assistant.code,
            scene_name=assistant.scene_name,
        )

    # ------------------------------------------------------------------
    # 渲染后回填
    # ------------------------------------------------------------------

    async def attach_video(
        self,
        *,
        message_id: str,
        video_url: str,
        duration_sec: float | None,
    ) -> None:
        await self.dao_msg.attach_video(
            message_id=message_id,
            video_url=video_url,
            duration_sec=duration_sec,
        )

    async def mark_render_failed(
        self,
        *,
        message_id: str,
        error: str,
    ) -> None:
        await self.dao_msg.mark_failed(
            message_id=message_id,
            status="failed",
            content="渲染失败",
            error=error,
        )

    async def mark_agent_failed(
        self,
        *,
        message_id: str,
        error: str,
    ) -> None:
        await self.dao_msg.mark_failed(
            message_id=message_id,
            status="failed",
            content="生成失败",
            error=error,
        )

    # ------------------------------------------------------------------
    # 私有
    # ------------------------------------------------------------------

    async def _run_agent(
        self,
        *,
        style: str,
        few_shots: Sequence[FewShot],
        on_event: OnEvent,
        prompt_text: str,
        user_id: str,
        conversation_id: str,
        extra_system_prompt: str = "",
        label: str = "agent.run",
    ) -> Message | None:
        """构造 agent → 跑 ``invoke_with_recovery`` → 拿回 middleware 创建的 assistant 消息。

        **必须**走 ``invoke_with_recovery`` 而非直接 ``agent.ainvoke`` —— 后者
        没有任何兜底，refine prompt 长 / LLM 把代码写到 thinking 块里时
        ``state["structured_response"]`` 经常为 None，4 层恢复链一个都用不上。
        ``invoke_with_recovery`` 在 ainvoke 之外再做 text-block / aggressive scan /
        python fence / 1-shot retry 的兜底，是 refine 路径能稳定出图的根。

        同一份 DAO 实例复用，避免每次新建 middleware 时再造一份 DAO。

        **长期记忆集成**：先 ``build_memory_block`` 拿用户偏好 + 历史 + 反馈，
        拼到 ``extra_system_prompt`` 末尾；agent 跑完后异步调
        ``extract_algorithm_name`` 把这次的算法名写回 user_algorithm_history。
        """
        # 拼 system prompt 的记忆块（空数据时自动空字符串）
        memory_block = await build_memory_block(
            self.session, user_id=user_id,
        )
        full_extra_prompt = (
            extra_system_prompt
            + ("\n\n" + memory_block if memory_block else "")
        )

        middleware = AgentPersistenceMiddleware(
            dao_steps=self.dao_steps,
            dao_messages=self.dao_msg,
        )
        agent = build_agent(
            style_id=style,
            extra_system_prompt=full_extra_prompt,
            few_shots=list(few_shots),
            middleware=[middleware],
        )
        recovered = await invoke_with_recovery(
            agent,
            {"messages": [HumanMessage(content=prompt_text)]},
            max_iterations=8,
            label=label,
            style_id=style,
            context={
                "conversation_id": conversation_id,
                "on_event": on_event,
            },
        )
        recovered_code: str | None = recovered.get("code") if recovered else None

        # middleware 的 ``aafter_agent`` 已经按 ``state["structured_response"]``
        # 写过一次 assistant 行。如果有 recovered code，需要再写一次把它从
        # ``status=failed`` 翻成 ``status=ok`` 并补 scene_name。
        assistant_msg = await self._get_assistant_after_agent(conversation_id)
        if recovered_code and assistant_msg is not None:
            await self.dao_msg.finalize_after_agent(
                message_id=assistant_msg.id,
                code=recovered_code,
                scene_name=_extract_scene_name(recovered_code),
                status="ok",
            )
            await self.session.refresh(assistant_msg)

        # 后台：触发 MemoryCurator 分析这次事件，提炼出 user_memories。
        # 失败只丢一条记忆，不影响主流程。
        self._schedule_memory_curator(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=assistant_msg.id if assistant_msg else None,
            user_prompt=prompt_text,
            code=recovered_code,
            status="ok" if recovered_code else "failed",
        )
        return assistant_msg

    def _schedule_memory_curator(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str | None,
        user_prompt: str,
        code: str | None,
        status: str,
    ) -> None:
        """Fire-and-forget 把这次生成作为事件丢给 MemoryCurator。

        Curator 会读 user 的现有 memories + 这次事件，调 LLM 输出
        add / reinforce / update / remove patch，应用到 user_memories。

        任一异常只 log —— 后台任务不应该让请求报错。
        """
        import asyncio
        from app.db.session import async_session_factory

        if not message_id:
            return

        async def _runner() -> None:
            try:
                summary = (
                    f"用户请求：{user_prompt[:300]}\n"
                    f"agent 生成代码（前 800 字）："
                    + (code or "")[:800]
                    + f"\n本次结果：{status}"
                )
                event = MemoryEvent(
                    kind="generation",
                    summary=summary,
                    extra={
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "status": status,
                    },
                )
                async with async_session_factory() as s:
                    curator = MemoryCurator(s)
                    n = await curator.process(event, user_id=user_id)
                logger.info(
                    "service.curator_invoked user=%s msg=%s actions=%d",
                    user_id, message_id, n,
                )
            except Exception:
                logger.exception("service.curator_failed user=%s", user_id)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_runner())
        except RuntimeError:
            asyncio.run(_runner())

    def schedule_feedback_curator(
        self,
        *,
        user_id: str,
        message_id: str,
        verdict: str,
        note: str | None = None,
        user_prompt: str = "",
        code: str = "",
    ) -> None:
        """公开方法 — 路由层调（POST /feedback 后）。"""
        import asyncio
        from app.db.session import async_session_factory

        async def _runner() -> None:
            try:
                summary = (
                    f"用户对 assistant message 给了反馈：verdict={verdict}。"
                    + (f" 注释：{note}" if note else "")
                    + (f"\n对应用户请求：{user_prompt[:200]}" if user_prompt else "")
                    + (f"\n对应生成代码（前 400 字）：{code[:400]}" if code else "")
                )
                event = MemoryEvent(
                    kind="feedback",
                    summary=summary,
                    extra={
                        "message_id": message_id,
                        "verdict": verdict,
                    },
                )
                async with async_session_factory() as s:
                    curator = MemoryCurator(s)
                    n = await curator.process(event, user_id=user_id)
                logger.info(
                    "service.feedback_curator user=%s msg=%s verdict=%s actions=%d",
                    user_id, message_id, verdict, n,
                )
            except Exception:
                logger.exception("service.feedback_curator_failed user=%s", user_id)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_runner())
        except RuntimeError:
            asyncio.run(_runner())

    def schedule_preference_curator(
        self,
        *,
        user_id: str,
        changed_fields: dict[str, str | None],
    ) -> None:
        """公开方法 — 路由层调（PUT /preferences 后）。"""
        import asyncio
        from app.db.session import async_session_factory

        async def _runner() -> None:
            try:
                summary = (
                    f"用户更新了偏好：{changed_fields}"
                )
                event = MemoryEvent(
                    kind="preference",
                    summary=summary,
                    extra={"changed_fields": changed_fields},
                )
                async with async_session_factory() as s:
                    curator = MemoryCurator(s)
                    n = await curator.process(event, user_id=user_id)
                logger.info(
                    "service.preference_curator user=%s actions=%d",
                    user_id, n,
                )
            except Exception:
                logger.exception(
                    "service.preference_curator_failed user=%s", user_id,
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_runner())
        except RuntimeError:
            asyncio.run(_runner())

    async def _get_assistant_after_agent(
        self, conversation_id: str,
    ) -> Message | None:
        """拿最近一条 assistant 消息（middleware 创建的那条）。"""
        from sqlalchemy import select

        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# refine prompt 组装
# ---------------------------------------------------------------------------

_REFINE_PREAMBLE = (
    "你现在处于【精细调整模式】。用户已经有一个能跑的 Manim 动画版本，下面是上一版代码。"
    "请只针对用户提出的调整要求做最小改动，其余代码保持原样。硬性约束：\n"
    "1. 必须保留 `from manim import *` 头\n"
    "2. Scene 类名尽量沿用（除非用户明确说要改名）\n"
    "3. 公式或库函数若发生改动，相应 import 跟保留\n"
    "4. 只输出完整新版本代码（CodeOutput{thought, code}），不要附加解释文字\n"
)


def _build_refine_prompt(
    prev_code: str,
    instruction: str,
    user_history: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if user_history:
        bullet = "\n".join(f"- {h}" for h in user_history)
        parts.append(f"[历史用户指令]\n{bullet}")
    parts.append(
        "[上一版代码]\n"
        "```python\n" + prev_code.rstrip() + "\n```"
    )
    parts.append("[本次用户调整要求]\n" + instruction.strip())
    return "\n\n".join(parts)


_SCENE_NAME_RE = re.compile(r"class\s+(\w+)\s*\(\s*Scene\s*\)")


def _extract_scene_name(code: str | None) -> str | None:
    """从 code 里正则抽出第一个 ``class Foo(Scene)`` 的类名。

    ``MessagesDAO.finalize_after_agent`` 已经把 scene_name 写进 assistant 行，
    service 不再用这个 helper——保留以便 tests / 调试。
    """
    if not code:
        return None
    m = _SCENE_NAME_RE.search(code)
    return m.group(1) if m else None


__all__ = ["AgentService", "AgentRunResult"]
