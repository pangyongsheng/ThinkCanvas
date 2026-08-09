"""HTTP routes for user-level long-term memory.

Endpoints
    - GET    /preferences       读当前用户偏好（不存在返回 null 字段）
    - PUT    /preferences       upsert 偏好（部分字段更新）
    - DELETE /preferences       重置偏好（一键清空）
    - POST   /feedback          用户对一条 assistant message 给 👍/👎/✏️

User scope 来自 ``X-User-Id`` header（``UserIdMiddleware`` 已经塞到
``request.state.user_id``）。所有 endpoint 不暴露 user_id 入参 ——
后端按 header 取，避免横向越权。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dao.user_feedback import UserFeedbackDAO
from app.agents.dao.user_preferences import UserPreferencesDAO
from app.agents.service import AgentService
from app.db.models import Message
from app.db.session import get_session
from app.storage import users as user_store


router = APIRouter(tags=["preferences"])
logger = logging.getLogger("thinkcanvas.api.preferences")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PreferencesOut(BaseModel):
    language: str | None = None
    default_style: str | None = None
    extra_instructions: str | None = None
    updated_at: str | None = None


class PreferencesUpdate(BaseModel):
    language: str | None = Field(default=None, max_length=8)
    default_style: str | None = Field(default=None, max_length=20)
    extra_instructions: str | None = Field(default=None, max_length=2000)


class FeedbackReq(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=26)
    verdict: str = Field(..., pattern=r"^(liked|disliked)$")
    note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_user(request: Request, session: AsyncSession) -> str:
    user_id = request.state.user_id
    await user_store.upsert_user(session, user_id)
    return user_id


# ---------------------------------------------------------------------------
# /preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user(request, session)
    pref = await UserPreferencesDAO(session).get(user_id)
    if pref is None:
        return PreferencesOut()
    return PreferencesOut(
        language=pref.language,
        default_style=pref.default_style,
        extra_instructions=pref.extra_instructions,
        updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
    )


@router.put("/preferences", response_model=PreferencesOut)
async def put_preferences(
    body: PreferencesUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user(request, session)
    pref = await UserPreferencesDAO(session).upsert(
        user_id=user_id,
        language=body.language,
        default_style=body.default_style,
        extra_instructions=body.extra_instructions,
    )
    # 异步触发 curator — 这次偏好变化让 LLM 决定是否强化 / 新增 / 更新 memory
    changed: dict[str, str | None] = {}
    if body.language is not None:
        changed["language"] = body.language
    if body.default_style is not None:
        changed["default_style"] = body.default_style
    if body.extra_instructions is not None:
        changed["extra_instructions"] = body.extra_instructions
    if changed:
        AgentService(session).schedule_preference_curator(
            user_id=user_id, changed_fields=changed,
        )
    return PreferencesOut(
        language=pref.language,
        default_style=pref.default_style,
        extra_instructions=pref.extra_instructions,
        updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
    )


@router.delete("/preferences", status_code=204)
async def delete_preferences(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user(request, session)
    ok = await UserPreferencesDAO(session).reset(user_id)
    # 没有偏好也是合法的（=204 而不是 404），reset 是幂等操作
    if not ok:
        await session.commit()
    return None


# ---------------------------------------------------------------------------
# /feedback
# ---------------------------------------------------------------------------

@router.post("/feedback", status_code=201)
async def post_feedback(
    body: FeedbackReq,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = await _resolve_user(request, session)

    # message 必须存在 + 必须是这个 user 的会话里的（防止横向）
    from sqlalchemy import select
    from app.db.models import Conversation
    stmt = (
        select(Message, Conversation.user_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == body.message_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    if row.user_id != user_id:
        raise HTTPException(status_code=403, detail="not your message")

    fb = await UserFeedbackDAO(session).write(
        user_id=user_id,
        message_id=body.message_id,
        verdict=body.verdict,
        note=body.note,
    )
    # 拉对应 message 的 user prompt / assistant code，给 curator 上下文
    from sqlalchemy import select
    from app.db.models import Message as MessageModel
    msg_row = (
        await session.execute(
            select(MessageModel).where(MessageModel.id == body.message_id)
        )
    ).scalar_one_or_none()
    user_prompt = ""
    code = ""
    if msg_row is not None and msg_row.conversation_id:
        prev_user = (
            await session.execute(
                select(MessageModel.content)
                .where(
                    MessageModel.conversation_id == msg_row.conversation_id,
                    MessageModel.role == "user",
                    MessageModel.created_at <= msg_row.created_at,
                )
                .order_by(MessageModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        user_prompt = prev_user or ""
        code = msg_row.code or ""
    AgentService(session).schedule_feedback_curator(
        user_id=user_id,
        message_id=body.message_id,
        verdict=body.verdict,
        note=body.note,
        user_prompt=user_prompt,
        code=code,
    )
    return {
        "id": fb.id,
        "message_id": fb.message_id,
        "verdict": fb.verdict,
        "note": fb.note,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }


__all__ = ["router"]


# ---------------------------------------------------------------------------
# /memories — 调试用：列出 active memories
# ---------------------------------------------------------------------------

@router.get("/memories")
async def list_memories(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """调试用 — 看 curator 当前为这个用户提炼出了什么 insights。

    按 confidence × recency 排序。
    """
    from app.agents.dao.user_memories import UserMemoriesDAO
    user_id = await _resolve_user(request, session)
    rows = await UserMemoriesDAO(session).list_active(user_id, limit=50)
    return {
        "user_id": user_id,
        "count": len(rows),
        "memories": [
            {
                "id": r.id,
                "category": r.category,
                "insight": r.insight,
                "confidence": r.confidence,
                "evidence_count": r.evidence_count,
                "last_reinforced_at": (
                    r.last_reinforced_at.isoformat()
                    if r.last_reinforced_at else None
                ),
            }
            for r in rows
        ],
    }
