"""HTTP routes for multi-turn conversations — 纯 Web 层。

职责（且仅限）：
  1. 接收 HTTP 请求、参数校验、用户身份校验
  2. 调 AgentService 跑 agent（middleware 自动落库）
  3. 调 Manim 渲染
  4. 把渲染结果回填到 assistant 消息（AgentService.attach_video）
  5. SSE 推送步骤事件 + 最终结果

所有 agent 业务、工具调用捕获、DB 写入都在 ``app.agents.*`` 里。
Web 层不接触任何 ORM / SQLAlchemy 表达式（除读取会话 id / 消息 id）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dao.conversations import ConversationsDAO
from app.agents.retriever import retrieve_similar_summaries
from app.agents.service import AgentService
from app.api.v1._sse_stream import OnEvent, stream_from_runner
from app.db.session import async_session_factory, get_session
from app.renderers.manim import render_code
from app.storage import users as user_store
from app.tools.validator import extract_scene_name


logger = logging.getLogger("thinkcanvas.api.conversations")

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas（请求 / 响应）
# ---------------------------------------------------------------------------


class CreateConversationReq(BaseModel):
    prompt: str
    style: str = "3b1b"


class RefineReq(BaseModel):
    instruction: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    code: str | None = None
    video_url: str | None = None
    scene_name: str | None = None
    duration_sec: float | None = None
    status: str
    error: str | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    style: str
    version: int
    phase: str = "coding"
    created_at: str
    updated_at: str


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
    current_script: dict | None = None


def _conv_to_out(c) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        title=c.title,
        style=c.style,
        version=c.version or 0,
        phase=getattr(c, "phase", None) or "coding",
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
    )


def _msg_to_out(m) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        code=m.code,
        video_url=m.video_url,
        scene_name=m.scene_name,
        duration_sec=m.duration_sec,
        status=m.status,
        error=m.error,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


async def _resolve_user_id(request: Request, session: AsyncSession) -> str:
    """读 ``request.state.user_id``，必要时 upsert 一行 User。"""
    user_id = request.state.user_id
    await user_store.upsert_user(session, user_id)
    return user_id


# ---------------------------------------------------------------------------
# /conversations  — 创建（首次生成）
# ---------------------------------------------------------------------------


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationReq,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """SSE 流：建会话 → 跑 agent（middleware 落库）→ 渲染 → 回填 video_url。"""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    user_id = await _resolve_user_id(request, session)
    style = req.style

    async def runner(on_event: OnEvent):
        # 1. 召回 few-shot
        async with async_session_factory() as s:
            few_shots = await retrieve_similar_summaries(
                s, prompt=prompt, style=style, top_k=2,
            )

        # 2. 跑 agent（middleware 自动落 agent_steps + 建/更新 assistant 消息）
        async with async_session_factory() as s:
            service = AgentService(s)
            try:
                run_result = await service.run_initial(
                    user_id=user_id,
                    prompt=prompt,
                    style=style,
                    few_shots=few_shots,
                    on_event=on_event,
                )
            except Exception as exc:
                logger.exception("create_conversation.run_initial failed")
                await on_event("failed", {"error": f"agent error: {exc}"})
                return

        # P3：scripting 阶段没出代码，把脚本推给用户
        if run_result.phase == "scripting" and run_result.script:
            await on_event("script_ready", {
                "script": run_result.script,
                "need_script": run_result.need_script,
                "conversation_id": run_result.conversation.id,
            })
            # 再发 done（前端 Promise 等 done 才 resolve，缺这个会卡死）
            await on_event("done", {
                "status": "script_ready",
                "conversation": _conv_to_out(run_result.conversation).model_dump(),
                "message": _msg_to_out(run_result.user_message).model_dump(),
                "assistant_message": None,
                "code": None,
                "video_url": None,
                "duration_sec": None,
                "scene_name": None,
                "script": run_result.script,
                "need_script": run_result.need_script,
            })
            return

        if not run_result.code:
            err = "agent failed to produce code"
            async with async_session_factory() as s:
                await AgentService(s).mark_agent_failed(
                    message_id=run_result.assistant_message.id,
                    error=err,
                )
            await on_event("failed", {"error": err})
            return

        scene_name = run_result.scene_name or extract_scene_name(run_result.code)
        await on_event("code", {"code": run_result.code, "scene_name": scene_name})
        await on_event("rendering", {"scene_name": scene_name})

        # 3. 渲染
        render_result = await render_code(run_result.code, scene_name)
        if render_result.error or not render_result.video_path:
            err = render_result.error or "no video"
            async with async_session_factory() as s:
                await AgentService(s).mark_render_failed(
                    message_id=run_result.assistant_message.id,
                    error=err,
                )
            await on_event("failed", {"error": err})
            return

        from app.api.v1.render import to_video_url
        video_url = to_video_url(render_result.video_path)

        # 4. 回填 video_url（assistant 消息已经在 middleware 里 finalize 过 code/status）
        async with async_session_factory() as s:
            await AgentService(s).attach_video(
                message_id=run_result.assistant_message.id,
                video_url=video_url,
                duration_sec=render_result.duration_sec,
            )

        # 5. done payload（前端要的全部信息）
        async with async_session_factory() as s:
            fresh = await ConversationsDAO(s).get(
                run_result.conversation.id, user_id=user_id,
            )
        await on_event("done", {
            "conversation": _conv_to_out(fresh).model_dump() if fresh else None,
            "message": _msg_to_out(run_result.user_message).model_dump(),
            "assistant_message": (
                _msg_to_out(run_result.assistant_message).model_dump()
                if run_result.assistant_message else None
            ),
            "code": run_result.code,
            "video_url": video_url,
            "duration_sec": render_result.duration_sec,
            "scene_name": scene_name,
        })

    return StreamingResponse(
        stream_from_runner(runner),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# /conversations/{id}/refine — 多轮调整
# ---------------------------------------------------------------------------


@router.post("/conversations/{conversation_id}/confirm")
async def confirm_conversation(
    conversation_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """用户确认脚本后调 — 续跑 phase=coding 的 supervisor（Coder → Reviewer）。

    返回 AgentRunResult 的 JSON（不走 SSE，简单同步）。
    """
    from app.agents.service import AgentService
    from app.agents.retriever import retrieve_similar_summaries
    from fastapi.responses import JSONResponse
    from app.agents.supervisor import PHASE_CODING

    user_id = await _resolve_user_id(request, session)

    # 召回 few-shot（基于 conv.title）
    async with async_session_factory() as s:
        conv = await s.get(__import__("app.db.models", fromlist=["Conversation"]).Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        few_shots = await retrieve_similar_summaries(
            s, prompt=conv.title or "", style=conv.style, top_k=2,
        )

    async with async_session_factory() as s:
        service = AgentService(s)
        try:
            run_result = await service.run_after_confirm(
                conversation_id=conversation_id,
                user_id=user_id,
                few_shots=few_shots,
            )
        except Exception as exc:
            logger.exception("confirm_conversation.run_after_confirm failed")
            raise HTTPException(status_code=500, detail=f"agent error: {exc}")

    if not run_result.code:
        raise HTTPException(status_code=409, detail="agent failed to produce code after confirm")

    scene_name = run_result.scene_name or extract_scene_name(run_result.code)

    # P3 修复：之前只返 code + scene_name，前端 getConversation 拿到
    # video_url=null → "视频还没渲染好" 卡死半小时。现在跟 create_conversation
    # 一样：跑 agent → 渲染 → attach_video → 一起返。
    render_result = await render_code(run_result.code, scene_name)
    if render_result.error or not render_result.video_path:
        err = render_result.error or "no video"
        async with async_session_factory() as s:
            await AgentService(s).mark_render_failed(
                message_id=run_result.assistant_message.id,
                error=err,
            )
        raise HTTPException(status_code=500, detail=f"render error: {err}")

    from app.api.v1.render import to_video_url
    video_url = to_video_url(render_result.video_path)
    async with async_session_factory() as s:
        await AgentService(s).attach_video(
            message_id=run_result.assistant_message.id,
            video_url=video_url,
            duration_sec=render_result.duration_sec,
        )

    return JSONResponse({
        "code": run_result.code,
        "scene_name": scene_name,
        "video_url": video_url,
        "duration_sec": render_result.duration_sec,
        "conversation_id": conversation_id,
    })


@router.post("/conversations/{conversation_id}/refine")
async def refine_conversation(
    request: Request,
    conversation_id: str,
    req: RefineReq,
    session: AsyncSession = Depends(get_session),
):
    """SSE 流：append user msg → 跑 refine agent → 渲染 → 回填。"""
    instruction = req.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is empty")

    user_id = await _resolve_user_id(request, session)
    dao = ConversationsDAO(session)
    conv = await dao.get(conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    # 找上一版代码
    latest_code: str | None = None
    for m in reversed(conv.messages):
        if m.role == "assistant" and m.code:
            latest_code = m.code
            break
    if not latest_code:
        raise HTTPException(
            status_code=409,
            detail="no previous code in conversation — generate first",
        )

    user_history = await dao.list_user_messages(conversation_id)
    style = conv.style

    async def runner(on_event: OnEvent):
        # 1. 召回 few-shot
        async with async_session_factory() as s:
            few_shots = await retrieve_similar_summaries(
                s, prompt=instruction, style=style, top_k=2,
            )

        # 2. 跑 refine agent
        async with async_session_factory() as s:
            try:
                run_result = await AgentService(s).run_refine(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    instruction=instruction,
                    prev_code=latest_code,
                    user_history=user_history,
                    style=style,
                    few_shots=few_shots,
                    on_event=on_event,
                )
            except Exception as exc:
                logger.exception("refine.run_refine failed")
                err = f"agent error: {exc}"
                # middleware 的 ``aafter_agent`` 之前已经把 DB 里的 assistant
                # shell 状态写成 ``failed``（code=None 时），无需额外处理。
                await on_event("failed", {"error": err})
                return

        if not run_result.code:
            err = "agent failed to produce code"
            async with async_session_factory() as s:
                await AgentService(s).mark_agent_failed(
                    message_id=run_result.assistant_message.id,
                    error=err,
                )
            await on_event("failed", {"error": err})
            return

        scene_name = run_result.scene_name or extract_scene_name(run_result.code)
        await on_event("code", {"code": run_result.code, "scene_name": scene_name})
        await on_event("rendering", {"scene_name": scene_name})

        # 3. 渲染
        render_result = await render_code(run_result.code, scene_name)
        if render_result.error or not render_result.video_path:
            err = render_result.error or "no video"
            async with async_session_factory() as s:
                await AgentService(s).mark_render_failed(
                    message_id=run_result.assistant_message.id,
                    error=err,
                )
            await on_event("failed", {"error": err})
            return

        from app.api.v1.render import to_video_url
        video_url = to_video_url(render_result.video_path)

        # 4. 回填
        async with async_session_factory() as s:
            await AgentService(s).attach_video(
                message_id=run_result.assistant_message.id,
                video_url=video_url,
                duration_sec=render_result.duration_sec,
            )

        await on_event("done", {
            "code": run_result.code,
            "video_url": video_url,
            "scene_name": scene_name,
            "duration_sec": render_result.duration_sec,
        })

    return StreamingResponse(
        stream_from_runner(
            runner,
            initial_events=[
                ("started", {"conversation_id": conversation_id}),
                ("generating", {"instruction": instruction}),
            ],
        ),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# /conversations — 读路径
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user_id(request, session)
    rows = await ConversationsDAO(session).list(
        user_id=user_id, limit=limit, offset=offset,
    )
    return [_conv_to_out(c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    request: Request,
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user_id(request, session)
    conv = await ConversationsDAO(session).get(conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetailOut(
        **_conv_to_out(conv).model_dump(),
        messages=[_msg_to_out(m) for m in conv.messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    request: Request,
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user_id(request, session)
    ok = await ConversationsDAO(session).delete(
        conversation_id, user_id=user_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    return None


__all__ = ["router"]
