"""HTTP routes for multi-turn conversations (v1.x).

Endpoints
    - POST   /conversations                       create + first user msg + first render
    - GET    /conversations                       list recent conversations (sidebar)
    - GET    /conversations/{id}                  fetch a conversation with messages
    - POST   /conversations/{id}/refine           SSE: refine the latest assistant code
    - DELETE /conversations/{id}                  delete conversation + cascading messages

The ``/refine`` endpoint emits the same SSE event shape as
``/generate/stream`` so the frontend can reuse the same handler for code /
rendering / done / failed transitions.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.refine import run_refine
from app.agents.react_coder import run_agent
from app.api.v1.render import to_video_url
from app.core.logging import log_exception
from app.db.models import Conversation, Message
from app.db.session import async_session_factory, get_session
from app.renderers.manim import render_code
from app.storage import conversations as conv_store
from app.tools.validator import extract_scene_name


router = APIRouter(tags=["conversations"])

logger = logging.getLogger("thinkcanvas.api")


# ---------- Schemas ----------

class CreateConversationReq(BaseModel):
    prompt: str
    style: str = "3b1b"


class RefineReq(BaseModel):
    instruction: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    code: str | None
    video_url: str | None
    scene_name: str | None
    duration_sec: float | None
    status: str
    error: str | None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    style: str
    version: int
    created_at: str
    updated_at: str


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class CreateConversationOut(BaseModel):
    conversation: ConversationOut
    message: MessageOut
    assistant_message: MessageOut | None = None
    code: str | None = None
    video_url: str | None = None
    duration_sec: float | None = None
    scene_name: str | None = None


# ---------- Helpers ----------

@asynccontextmanager
async def _open_session() -> AsyncIterator[AsyncSession]:
    """Fresh session — used inside the SSE generator after FastAPI's
    dependency-injected session is already closed.
    """
    async with async_session_factory() as s:
        yield s


def _msg_to_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        code=m.code,
        video_url=m.video_url,
        scene_name=m.scene_name,
        duration_sec=float(m.duration_sec) if m.duration_sec is not None else None,
        status=m.status,
        error=m.error,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


def _conv_to_out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        title=c.title,
        style=c.style,
        version=c.version,
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
    )


async def _render_initial(
    session: AsyncSession,
    *,
    conversation_id: str,
    style: str,
    prompt: str,
) -> tuple[str | None, str | None, str | None, float | None, Message]:
    """Run agent + renderer, persist the assistant message, return
    ``(code, video_url, scene_name, duration_sec, assistant_message)``.
    """
    result = await run_agent(prompt, style_id=style, max_iterations=8)
    code = result.get("code")

    if not code:
        msg = await conv_store.write_assistant_message(
            session, conversation_id, status="failed", content="生成失败", error="agent failed to produce code"
        )
        return None, None, None, None, msg

    scene_name = extract_scene_name(code)
    render_result = await render_code(code, scene_name)

    if render_result.error or not render_result.video_path:
        err = render_result.error or "no video"
        msg = await conv_store.write_assistant_message(
            session,
            conversation_id,
            status="failed",
            content="渲染失败",
            code=code,
            scene_name=scene_name,
            duration_sec=render_result.duration_sec,
            error=err,
        )
        return code, None, scene_name, render_result.duration_sec, msg

    video_url = to_video_url(render_result.video_path)
    msg = await conv_store.write_assistant_message(
        session,
        conversation_id,
        status="ok",
        content="生成成功",
        code=code,
        video_url=video_url,
        scene_name=scene_name,
        duration_sec=render_result.duration_sec,
    )
    return code, video_url, scene_name, render_result.duration_sec, msg


# ---------- Routes ----------

@router.post("/conversations", response_model=CreateConversationOut)
async def create_conversation(
    req: CreateConversationReq,
    session: AsyncSession = Depends(get_session),
) -> CreateConversationOut:
    """Create a conversation + first user message + first render in one shot."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    conv = await conv_store.create_conversation(session, prompt=prompt, style=req.style)
    code, video_url, scene_name, duration_sec, assistant_msg = await _render_initial(
        session,
        conversation_id=conv.id,
        style=req.style,
        prompt=prompt,
    )

    # Open a fresh session for the final read so we don't trigger
    # lazy-load IO on a session that's already been used past the
    # dependency boundary.
    async with _open_session() as s:
        fresh = await conv_store.get_conversation(s, conv.id)
    first_user_msg = fresh.messages[0] if fresh and fresh.messages else None
    if first_user_msg is None:
        raise HTTPException(status_code=500, detail="first user message missing")

    return CreateConversationOut(
        conversation=_conv_to_out(fresh),
        message=_msg_to_out(first_user_msg),
        assistant_message=_msg_to_out(assistant_msg) if assistant_msg else None,
        code=code,
        video_url=video_url,
        duration_sec=duration_sec,
        scene_name=scene_name,
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    rows = await conv_store.list_conversations(session, limit=limit, offset=offset)
    return [_conv_to_out(c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConversationDetailOut:
    conv = await conv_store.get_conversation(session, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetailOut(
        **_conv_to_out(conv).model_dump(),
        messages=[_msg_to_out(m) for m in conv.messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
):
    ok = await conv_store.delete_conversation(session, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    return None


@router.post("/conversations/{conversation_id}/refine")
async def refine_conversation(
    conversation_id: str,
    req: RefineReq,
    session: AsyncSession = Depends(get_session),
):
    """SSE stream that runs refine + render for a single conversation."""
    instruction = req.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is empty")

    conv = await conv_store.get_conversation(session, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    # Extract everything we need from the ORM object *now* (before the
    # session gets reused for other writes or closes) so the SSE
    # generator doesn't trigger any lazy load on a dead session.
    style = conv.style

    # Latest assistant code in this conversation is what we refine on top of.
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

    user_msg = await conv_store.append_user_message(session, conversation_id, instruction)
    user_msg_id = user_msg.id

    async def event_generator():
        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield _sse("started", {"conversation_id": conversation_id, "user_message_id": user_msg_id})
            yield _sse("generating", {"instruction": instruction})

            result = await run_refine(latest_code, instruction, style_id=style, max_iterations=6)
            code = result.get("code")
            tool_calls = len(result.get("tool_log", []))

            if not code:
                last_msg = str(result.get("messages", [])[-1])[:400] if result.get("messages") else ""
                async with _open_session() as s:
                    await conv_store.write_assistant_message(
                        s, conversation_id, status="failed",
                        content="调整失败：模型未生成代码",
                        error="agent failed to produce code",
                    )
                yield _sse(
                    "failed",
                    {"error": "agent failed to produce code", "tool_calls": tool_calls, "last_message": last_msg},
                )
                return

            scene_name = extract_scene_name(code)
            yield _sse("code", {"code": code, "scene_name": scene_name})

            render_result = await render_code(code, scene_name)
            if render_result.error or not render_result.video_path:
                err = render_result.error or "no video"
                async with _open_session() as s:
                    await conv_store.write_assistant_message(
                        s, conversation_id, status="failed",
                        content="渲染失败",
                        code=code, scene_name=scene_name,
                        duration_sec=render_result.duration_sec,
                        error=err,
                    )
                yield _sse("failed", {"error": err})
                return

            video_url = to_video_url(render_result.video_path)
            async with _open_session() as s:
                await conv_store.write_assistant_message(
                    s, conversation_id, status="ok",
                    content="调整完成",
                    code=code, video_url=video_url,
                    scene_name=scene_name,
                    duration_sec=render_result.duration_sec,
                )
            yield _sse(
                "done",
                {
                    "code": code,
                    "video_url": video_url,
                    "scene_name": scene_name,
                    "duration_sec": render_result.duration_sec,
                },
            )
        except Exception:
            log_exception(logger, "conversations/refine unhandled", conv=conversation_id)
            try:
                async with _open_session() as s:
                    await conv_store.write_assistant_message(
                        s, conversation_id, status="failed",
                        content="internal error",
                        error="internal server error",
                    )
            except Exception:
                log_exception(logger, "failed to persist refine failure")
            yield _sse("failed", {"error": "internal server error"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router"]
