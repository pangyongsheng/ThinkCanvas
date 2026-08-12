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
from typing import Optional, Sequence

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.algorithm_extractor import extract_algorithm_name
from app.agents.supervisor import PHASE_CODING, PHASE_SCRIPTING, build_supervisor
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
    """Service 跑一次 agent 后的返回值 — 路由层拿到这个再渲染 + 回填。

    P3 加字段：
      * phase       — 跑完时 conversation 处于哪个 phase
      * script      — 当前脚本（scripting 阶段才有，coding 阶段为 None）
      * need_script — 入口分诊是否判定"需要脚本"（前端弹脚本面板用）
    
    P3 修正：``assistant_message`` 在 scripting 阶段可能为 ``None``
    （Script Designer 停了、Coder 没跑，middleware 没建 assistant 壳）。
    路由层只会在 ``phase == "coding"`` 时用它；scripting 阶段走
    ``script_ready`` SSE 分支，不碰 ``assistant_message``。
    """
    conversation: Conversation
    user_message: Message
    assistant_message: Optional[Message]
    code: str | None
    scene_name: str | None
    error: str | None = None
    phase: str = PHASE_CODING
    script: dict | None = None
    need_script: bool = False


def _require_message(
    label: str,
    msg: Message | None,
    conversation_id: str,
) -> Message:
    """断言 helper：Coding 阶段（``abefore_agent`` 跑过）assistant 壳必有；
    Scripting 阶段 Script Designer 停了 Coder 没跑，可能为 None，
    调用方需自行分支处理（见 ``AgentService.run_initial``）。
    """
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
        phase: str = PHASE_SCRIPTING,
    ) -> AgentRunResult:
        """建会话 + user 消息 → 跑 agent → middleware 自动落库。

        P3 默认 phase=scripting：会先跑 Script Designer 决定要不要
        出脚本。脚本出完停在这（service 返回 phase=scripting + script
        字段），路由层把脚本推给用户确认。用户点确认后调
        ``run_after_confirm`` 续跑（phase=coding）。
        """
        conv = await self.dao_conv.create(
            prompt=prompt, style=style, user_id=user_id,
        )
        # 标记 phase
        await self.dao_conv.set_phase(conv.id, phase)
        user_msg = await self.dao_msg.append_user_message(
            conversation_id=conv.id, content=prompt,
        )
        assistant_msg, run_state = await self._run_agent(
            style=style,
            few_shots=few_shots,
            on_event=on_event,
            prompt_text=prompt.strip(),
            user_id=user_id,
            conversation_id=conv.id,
            label="agent.run_initial",
            phase=phase,
        )
        # 写回 current_script + 切换 phase
        script = (run_state or {}).get("current_script")
        final_phase = (run_state or {}).get("phase") or phase
        await self.dao_conv.update_after_run(
            conversation_id=conv.id,
            phase=final_phase,
            current_script=script,
        )
        # P3：scripting 阶段 Script Designer 停了、Coder 没跑，
        # middleware 没建 assistant 壳 — 不强制要求。
        # coding 阶段 Coder 一定跑过，assistant_msg 必有。
        if final_phase == PHASE_SCRIPTING:
            assistant: Message | None = assistant_msg
        else:
            assistant = _require_message(
                "run_initial", assistant_msg, conv.id,
            )
        return AgentRunResult(
            conversation=conv,
            user_message=user_msg,
            assistant_message=assistant,
            code=assistant.code if assistant is not None else None,
            scene_name=assistant.scene_name if assistant is not None else None,
            phase=final_phase,
            script=script,
            need_script=bool((run_state or {}).get("need_script", False)),
        )

    async def run_after_confirm(
        self,
        *,
        conversation_id: str,
        user_id: str,
        few_shots: Sequence[FewShot] = (),
        on_event: OnEvent = None,
    ) -> AgentRunResult:
        """用户确认脚本后调，phase=coding，跳过 Script Designer 走 Coder。"""
        # 拿到 conv + 已确认的 script
        conv = await self.dao_conv.get(conversation_id, user_id=user_id)
        if conv is None:
            raise ValueError(f"conversation {conversation_id} not found for user {user_id}")
        if conv.phase != PHASE_SCRIPTING:
            raise ValueError(f"conversation {conversation_id} not in scripting phase (current={conv.phase})")
        # 把 conv.phase 标为 coding（用户已确认）
        await self.dao_conv.set_phase(conversation_id, PHASE_CODING)
        prompt_text = (conv.title or "").strip() or "请基于脚本生成动画"
        assistant_msg, run_state = await self._run_agent(
            style=conv.style,
            few_shots=few_shots,
            on_event=on_event,
            prompt_text=prompt_text,
            user_id=user_id,
            conversation_id=conv.id,
            label="agent.run_after_confirm",
            phase=PHASE_CODING,
        )
        assistant = _require_message("run_after_confirm", assistant_msg, conv.id)
        # coding 阶段结束，标 done
        await self.dao_conv.update_after_run(
            conversation_id=conv.id,
            phase=PHASE_CODING,
            current_script=conv.current_script,
        )
        return AgentRunResult(
            conversation=conv,
            user_message=None,  # 没新增 user 消息
            assistant_message=assistant,
            code=assistant.code if assistant is not None else None,
            scene_name=assistant.scene_name if assistant is not None else None,
            phase=PHASE_CODING,
            script=conv.current_script,
            need_script=False,
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
        assistant_msg, _ = await self._run_agent(
            style=style,
            few_shots=few_shots,
            on_event=on_event,
            prompt_text=prompt_text,
            user_id=user_id,
            conversation_id=conversation_id,
            extra_system_prompt=_REFINE_PREAMBLE,
            label="agent.run_refine",
            phase=PHASE_CODING,
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
            code=assistant.code if assistant is not None else None,
            scene_name=assistant.scene_name if assistant is not None else None,
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
        phase: str = PHASE_CODING,
    ) -> tuple[Message | None, dict | None]:
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
        # P3：phase 必须传给 build_supervisor，否则图默认 PHASE_SCRIPTING，
        # confirm 路径传 PHASE_CODING 也被忽略 — 还是会先跑 script_decision，
        # Coder 没机会跑，_require_message 抛 RuntimeError。
        supervisor = build_supervisor(
            style_id=style,
            extra_system_prompt=full_extra_prompt,
            few_shots=list(few_shots),
            middleware=[middleware],
            phase=phase,
        )
        # Supervisor 走 state 路径：conversation_id / on_event 塞进 state，
        # 因为 Supervisor 把 worker 当 subgraph 调用时 runtime.context 不会
        # 透传。同时也通过 context 参数传一份，老路径仍能拿到。
        supervisor_input = {
            "messages": [HumanMessage(content=prompt_text)],
            "conversation_id": conversation_id,
            "on_event": on_event,
            "code_round": 0,
        }
        # P2 Supervisor 是 StateGraph 图，Coder / Reviewer 都是 node。
        # Coder 内部已自带 ``invoke_with_recovery`` 兜底（4 层 + 3 次重试），
        # 所以这里不用再包一层，直接 ainvoke 即可。
        try:
            final_state = await supervisor.ainvoke(
                supervisor_input,
                config={"recursion_limit": 30},
                context={
                    "conversation_id": conversation_id,
                    "on_event": on_event,
                },
            )
        except Exception as exc:
            # 任何 supervisor.ainvoke 异常（middleware ValueError / LLM /
            # 工具调用失败 / DB 失败）都先把 session rollback 救回来，
            # 再把 assistant 消息标 failed，避免下一次写入踩
            # InFailedSQLTransactionError 整个请求挂掉。
            try:
                await self.session.rollback()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "service._run_agent.rollback_failed conversation=%s",
                    conversation_id,
                )
            assistant_msg = await self._get_assistant_after_agent(
                conversation_id,
            )
            if assistant_msg is not None:
                await self.dao_msg.mark_failed(
                    message_id=assistant_msg.id,
                    status="failed",
                    content="生成失败",
                    error=str(exc)[:1000],
                )
                await self.session.commit()
            logger.exception(
                "service._run_agent.failed conversation=%s err=%s",
                conversation_id, exc,
            )
            raise
        # P3 state：code / thought / scene_name / review / code_round / script / phase
        recovered_code: str | None = (final_state or {}).get("code") or None
        final_review = (final_state or {}).get("review")
        rounds = int((final_state or {}).get("code_round", 0))

        # 记 P2 审查结果到日志（不在 DB 里持久化，调试用）
        if final_review is not None:
            logger.info(
                "service.p2.review conversation=%s rounds=%d ok=%s feedback_len=%d",
                conversation_id, rounds, final_review.ok, len(final_review.feedback or ""),
            )

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
        return assistant_msg, final_state

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
