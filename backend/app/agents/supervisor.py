"""Supervisor 编排 — 整个项目用 LangGraph 图驱动多 Agent 协作。

P1 (已上线):  只有 Coder 1 个 worker。``build_supervisor`` 直接返回 Coder。

P2 (当前):   Coder → Reviewer 循环。Reviewer 审代码不通过就让 Coder 重写，
              最多 2 轮。流程是固定的（Coder ↔ Reviewer），用图驱动
              （条件边）比真 Supervisor (LLM 决策) 更可预测，避免
              langgraph_supervisor 包裹 worker 时的 greenlet 边界问题。

P3+ (规划):  入口分流（简单走 Coder / 复杂走 Script Designer）— 那时
              流程不再固定，切换到 ``langgraph_supervisor.create_supervisor``
              走真 Supervisor LLM 决策。

P2 架构图：

  [__start__] → Coder → Reviewer ── ok 或 round≥2 ─→ [__end__]
                                  └─ 不ok && round<2 ─→ Coder (附 feedback)

  * Coder    — 写 Manim 代码（validate + render tools），返回 CodeOutput.code
  * Reviewer — 纯 LLM 审代码，返回 CodeReview{ok, feedback}
  * 条件边   — Reviewer 后根据 ok / code_round 决定走 finish 还是回 Coder

State schema：

  * messages:        标准（HumanMessage / AIMessage / ...）
  * conversation_id: 给中间件落库用
  * on_event:        SSE 回调
  * code:            Coder 输出（Reviewer 拿这个审）
  * review:          Reviewer 输出
  * code_round:      0, 1, 2（cap 在 MAX_CODE_ROUNDS）

中间件：只挂 Coder（两轮 Coder 都会重建 worker 挂同一份 middleware，
分别落不同 message row）。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.agents.agent_recovery import invoke_with_recovery
from app.agents.builder import _compose_system_prompt
from pydantic import BaseModel, Field
from app.agents.reviewer import (
    CodeReview,
    build_reviewer_prompt,
    build_reviewer_user_message,
)
from app.agents.schemas import CodeOutput
from app.agents.script_designer import (
    SceneScript,
    build_script_designer_prompt,
    build_script_designer_user_message,
)
from app.agents.styles import DEFAULT_STYLE_ID
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.db.models import FewShot
from app.llm.client import get_llm

# phase 常量
PHASE_SCRIPTING = "scripting"
PHASE_CODING = "coding"
PHASE_DONE = "done"


# ---------------------------------------------------------------------------
# 常量 / State
# ---------------------------------------------------------------------------


MAX_CODE_ROUNDS = 2  # Coder 最多跑 2 次（首轮 + 1 次 retry）


class SupervisorState(TypedDict, total=False):
    """P3 Supervisor 图的 state schema。"""

    messages: Annotated[list, add_messages]
    conversation_id: str
    on_event: Any  # Callable[[str, dict], Awaitable[None]] | None
    # P3 阶段控制
    phase: str  # PHASE_SCRIPTING / PHASE_CODING / PHASE_DONE
    current_script: dict  # SceneScript.model_dump() 结果
    script_confirmed: bool  # 用户是否已确认脚本
    need_script: bool  # Supervisor 决定要不要走 Script Designer
    skip_script: bool  # 用户从外部说"这个直接出代码"（备用，目前没用）
    # Coder 输出
    code: str
    thought: str
    scene_name: str
    # Reviewer 输出
    review: CodeReview
    # 轮次
    code_round: int  # 0 = 首轮；每次回 Coder +1
    # 上一轮 Reviewer 的反馈（让 Coder 第二轮能看到"上次哪里错"）
    previous_feedback: str


_SCENE_NAME_RE = re.compile(r"class\s+(\w+)\s*\(\s*Scene\s*\)")


def _extract_scene_name(code: str | None) -> str | None:
    if not code:
        return None
    m = _SCENE_NAME_RE.search(code)
    return m.group(1) if m else None


def _extract_thought(messages: Sequence) -> str:
    """从最后一条非空 AIMessage content 拿 thought。"""
    for m in reversed(list(messages)):
        content = getattr(m, "content", "")
        if isinstance(content, str) and content.strip():
            return content[:300]
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") in {"text", "output_text"}:
                    txt = blk.get("text") or ""
                    if txt.strip():
                        return txt[:300]
    return ""


# ---------------------------------------------------------------------------
# Worker 工厂
# ---------------------------------------------------------------------------


def build_coder_worker(
    *,
    style_id: str = DEFAULT_STYLE_ID,
    extra_system_prompt: str = "",
    few_shots: Sequence[FewShot] = (),
    middleware: Sequence = (),
):
    """构造 Coder worker — ReAct agent with validate + render tools。"""
    system_prompt = _compose_system_prompt(
        style_id=style_id,
        extra_system_prompt=extra_system_prompt,
        few_shots=few_shots,
    )
    return create_agent(
        model=get_llm(),
        tools=[validate_manim_code, render_manim_dryrun],
        system_prompt=system_prompt,
        response_format=CodeOutput,
        middleware=list(middleware),
        name="coder",
    )


def build_reviewer_llm():
    """Reviewer 纯 LLM（无工具），``with_structured_output(CodeReview)`` 拿结构化。"""
    return get_llm().with_structured_output(CodeReview)


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def _make_coder_node(
    *,
    style_id: str,
    extra_system_prompt: str,
    few_shots: Sequence[FewShot],
    middleware: Sequence,
):
    """返回绑定了 style / extra / few-shots / middleware 的 Coder node 闭包。"""
    async def _coder_node(state: SupervisorState) -> dict:
        review_feedback = state.get("previous_feedback", "")
        full_extra = extra_system_prompt
        if review_feedback:
            full_extra = (
                (full_extra + "\n\n" if full_extra else "")
                + "【审查反馈 — 必须修正】\n"
                + review_feedback.strip()
            )
        worker = build_coder_worker(
            style_id=style_id,
            extra_system_prompt=full_extra,
            few_shots=few_shots,
            middleware=middleware,
        )
        result = await invoke_with_recovery(
            worker,
            {"messages": list(state.get("messages") or [])},
            max_iterations=8,
            label="agent.p2.coder",
            style_id=style_id,
            context={
                "conversation_id": state.get("conversation_id", ""),
                "on_event": state.get("on_event"),
            },
        )
        code = (result.get("code") if result else None) or ""
        thought = _extract_thought(result.get("messages") if result else [])
        return {
            "code": code,
            "thought": thought,
            "scene_name": _extract_scene_name(code) or "",
            "code_round": int(state.get("code_round", 0)) + 1,
        }
    return _coder_node


async def _reviewer_node(state: SupervisorState) -> dict:
    """跑 Reviewer LLM，输出 CodeReview 写进 state。

    解析失败 fallback：MiniMax-M3 经常不严格走 JSON schema，直接吐
    "OK 看着没问题" 这类纯文本。解析失败时 fallback ``ok=True`` —
    Coder 内部已经 validate + render 过，外部 Reviewer 解析失败
    不等于代码真有问题，强行打回只会浪费 1 轮 retry。
    """
    import logging
    logger = logging.getLogger("thinkcanvas.agents.supervisor")
    llm = build_reviewer_llm()
    prev_feedback = ""
    if state.get("review") is not None:
        prev_feedback = (state.get("review") or CodeReview(ok=True, feedback="")).feedback
    user_msg = build_reviewer_user_message(
        code=state.get("code", ""),
        previous_feedback=prev_feedback,
    )
    messages: list = [
        SystemMessage(content=build_reviewer_prompt()),
        HumanMessage(content=user_msg),
    ]
    try:
        review: CodeReview = await llm.ainvoke(messages)
    except Exception as exc:
        # 解析失败 / LLM 输出格式不对 — fallback 通过，不阻塞主流程
        logger.warning(
            "supervisor.reviewer.parse_failed conversation=%s err=%s — fallback ok=True",
            state.get("conversation_id", ""), type(exc).__name__,
        )
        return {"review": CodeReview(ok=True, feedback="")}
    update: dict = {"review": review}
    # 不通过就把 feedback 提前写进 state — router 只返 string，
    # state update 不能放 router 里（LangGraph 用 router 返回值当 ends key，
    # dict 不可 hash → TypeError）。
    if not review.ok:
        update["previous_feedback"] = (
            review.feedback or "审查未通过，请根据上面要求修正。"
        )
    return update


def _route_after_reviewer(state: SupervisorState) -> Literal["coder", "__end__"]:
    """Reviewer 之后的条件边 — 只返 string，不能返 state update。"""
    review = state.get("review")
    if review is None:
        return "__end__"
    if review.ok:
        return "__end__"
    if int(state.get("code_round", 0)) >= MAX_CODE_ROUNDS:
        return "__end__"
    return "coder"


# ---------------------------------------------------------------------------
# P3 · Script Designer node + 入口路由
# ---------------------------------------------------------------------------


SCRIPT_DESIGNER_SYSTEM_DECISION_PROMPT = (
    "你是 ThinkCanvas 的总入口分诊。\n"
    "\n"
    "看用户的 prompt，决定要不要先调 Script Designer 出脚本给人确认。\n"
    "\n"
    "【需要脚本 — 回复 need_script=true】\n"
    "  * 概念抽象（解释 XX 的物理意义 / 展示 XX 的几何直觉）\n"
    "  * 用户没明确步骤（做个微积分 / 讲讲贝叶斯）\n"
    "  * 内容比较长 / 复杂（展示 XX + 一个例子 / 分三段讲）\n"
    "  * 风格 / 视觉 / 表达方式 用户没明说\n"
    "\n"
    "【不需要脚本 — 回复 need_script=false】\n"
    "  * 明确单一的算法（冒泡排序 / 二分查找 / 图 BFS）\n"
    "  * 用户给了具体步骤（先建圆、再画切线）\n"
    "  * 调整现有动画的明确指令（颜色改红 / 速度变快）\n"
    "\n"
    "【输出格式 — 严格 JSON】\n"
    "只输出一个 JSON 对象：\n"
    "  {”need_script“: true, ”reason“: ”一句话理由“} 或\n"
    "  {”need_script“: false, ”reason“: ”一句话理由“}\n"
    "\n"
    "不要其他文字。"
)


class ScriptDecision(BaseModel):
    """Script Designer 入口分诊结果。"""

    need_script: bool
    reason: str = Field(default="", max_length=200)


async def _script_decision_node(state: SupervisorState) -> dict:
    """入口分诊节点：判断要不要出脚本。

    解析失败 fallback need_script=True（复杂时宁可多走一步也别漏），
    跟 Reviewer fallback ok=True 的逻辑对称。
    """
    import logging
    logger = logging.getLogger("thinkcanvas.agents.supervisor")
    llm = get_llm().with_structured_output(ScriptDecision)
    msgs: list = [
        SystemMessage(content=SCRIPT_DESIGNER_SYSTEM_DECISION_PROMPT),
        HumanMessage(content=state.get("messages", [{}])[-1].content if state.get("messages") else ""),
    ]
    try:
        decision: ScriptDecision = await llm.ainvoke(msgs)
    except Exception as exc:
        logger.warning(
            "supervisor.script_decision.parse_failed conversation=%s err=%s — fallback need_script=True",
            state.get("conversation_id", ""), type(exc).__name__,
        )
        decision = ScriptDecision(need_script=True, reason="分诊失败，按复杂走")
    return {
        "need_script": decision.need_script,
        "phase": PHASE_SCRIPTING if decision.need_script else PHASE_CODING,
    }


async def _script_designer_node(state: SupervisorState) -> dict:
    """Script Designer 出脚本（结构化输出）。"""
    import logging
    logger = logging.getLogger("thinkcanvas.agents.supervisor")
    llm = get_llm().with_structured_output(SceneScript)
    user_prompt = ""
    if state.get("messages"):
        user_prompt = state["messages"][-1].content
    msgs: list = [
        SystemMessage(content=build_script_designer_prompt()),
        HumanMessage(content=build_script_designer_user_message(user_prompt)),
    ]
    try:
        script: SceneScript = await llm.ainvoke(msgs)
        return {
            "current_script": script.model_dump(),
            "phase": PHASE_SCRIPTING,  # 等用户确认
        }
    except Exception as exc:
        logger.warning(
            "supervisor.script_designer.parse_failed conversation=%s err=%s",
            state.get("conversation_id", ""), type(exc).__name__,
        )
        # 解析失败时给个空 script 让上层能 fallback 到 coding
        return {
            "current_script": None,
            "phase": PHASE_CODING,
        }


def _entry_router(state: SupervisorState) -> Literal["script_decision", "coder"]:
    """P3 入口：根据 phase 决定从哪开始。

    phase=scripting — 第一次跑，先进 Script Designer 决定
    phase=coding   — 已确认脚本或跳过脚本，直接进 Coder
    """
    phase = state.get("phase", "")
    if phase == PHASE_CODING or state.get("script_confirmed"):
        return "coder"
    if phase == PHASE_DONE:
        return "coder"  # 已完成的会话不会再跑这图
    return "script_decision"


def _after_decision_router(state: SupervisorState) -> Literal["script_designer", "coder"]:
    """Script Designer 分诊后的分支。"""
    if state.get("need_script"):
        return "script_designer"
    return "coder"


def _after_script_router(state: SupervisorState) -> Literal["coder", "__end__"]:
    """Script Designer 出脚本后停在这 — 等用户确认。

    用户点"确认"后调 POST /conversations/{id}/confirm，那条路由
    会再次跑 supervisor（这次 phase=coding），自然进 coder。
    """
    return "__end__"


def build_supervisor(
    *,
    style_id: str = DEFAULT_STYLE_ID,
    extra_system_prompt: str = "",
    few_shots: Sequence[FewShot] = (),
    middleware: Sequence = (),
    phase: str = PHASE_SCRIPTING,
):
    """构造 P3 Supervisor 图（Coder ↔ Reviewer + Script Designer 入口）。

    P3 三阶段路由：

      [__start__] → entry_router → script_decision → after_decision_router
                                                            ↓
                                                  ┌─────────┴─────────┐
                                                  ↓                   ↓
                                            script_designer       coder → reviewer
                                                  ↓
                                          after_script_router
                                                  ↓
                                              [__end__]   (等用户确认)

    参数 phase 决定从 script_decision 还是 coder 起跑：
      * phase=scripting (默认) — 第一次跑，从 script_decision 起
      * phase=coding — 用户已确认脚本（或脚本阶段被跳过），从 coder 起
    """
    from app.agents.script_designer import SceneScript as _SceneScript  # noqa
    coder_node = _make_coder_node(
        style_id=style_id,
        extra_system_prompt=extra_system_prompt,
        few_shots=few_shots,
        middleware=middleware,
    )
    g = StateGraph(SupervisorState)
    g.add_node("script_decision", _script_decision_node)
    g.add_node("script_designer", _script_designer_node)
    g.add_node("coder", coder_node)
    g.add_node("reviewer", _reviewer_node)
    # 入口 — 用条件路由根据 phase 起
    g.add_conditional_edges(
        START,
        lambda state: "coder" if phase == PHASE_CODING else "script_decision",
        {"coder": "coder", "script_decision": "script_decision"},
    )
    # 分诊 → 出脚本 / 直接 Coder
    g.add_conditional_edges(
        "script_decision",
        _after_decision_router,
        {"script_designer": "script_designer", "coder": "coder"},
    )
    # 出完脚本 → 等用户确认（停在这）
    g.add_conditional_edges(
        "script_designer",
        _after_script_router,
        {"coder": "coder", "__end__": END},
    )
    # Coder → Reviewer 循环（P2 已有）
    g.add_edge("coder", "reviewer")
    g.add_conditional_edges(
        "reviewer",
        _route_after_reviewer,
        {"coder": "coder", "__end__": END},
    )
    return g.compile()
    coder_node = _make_coder_node(
        style_id=style_id,
        extra_system_prompt=extra_system_prompt,
        few_shots=few_shots,
        middleware=middleware,
    )
    g = StateGraph(SupervisorState)
    g.add_node("coder", coder_node)
    g.add_node("reviewer", _reviewer_node)
    g.add_edge(START, "coder")
    g.add_edge("coder", "reviewer")
    g.add_conditional_edges(
        "reviewer",
        _route_after_reviewer,
        {"coder": "coder", "__end__": END},
    )
    return g.compile()


__all__ = [
    "build_supervisor",
    "build_coder_worker",
    "build_reviewer_llm",
    "SupervisorState",
    "MAX_CODE_ROUNDS",
    "PHASE_SCRIPTING",
    "PHASE_CODING",
    "PHASE_DONE",
    "ScriptDecision",
]
