"""HTTP routes for the curated ``few_shots`` pool.

Endpoints
    - POST /few_shots        save a (prompt, code, style) triple
    - GET  /few_shots        list curated examples (optionally filtered by style)

The whole table is shared (single-user project). The frontend's
"👍 收藏为范例" button on each assistant message POSTs here; the
future prompt-builder will GET to retrieve candidates.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FewShot
from app.db.session import get_session
from app.agents.summarizer import summarise_few_shot
from app.storage import few_shots as fs_store


router = APIRouter(tags=["few_shots"])


# ---------- Schemas ----------

class CreateFewShotReq(BaseModel):
    prompt: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    style: str = Field(..., min_length=1)
    source_conversation_id: Optional[str] = None
    source_message_id: Optional[str] = None


class FewShotOut(BaseModel):
    id: str
    prompt: str
    code: str
    summary: str
    style: str
    source_conversation_id: Optional[str]
    source_message_id: Optional[str]
    created_at: str


def _to_out(row: FewShot) -> FewShotOut:
    return FewShotOut(
        id=row.id,
        prompt=row.prompt,
        code=row.code,
        summary=row.summary,
        style=row.style,
        source_conversation_id=row.source_conversation_id,
        source_message_id=row.source_message_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


# ---------- Routes ----------

@router.post("/few_shots", response_model=FewShotOut, status_code=201)
async def create_few_shot(
    req: CreateFewShotReq,
    session: AsyncSession = Depends(get_session),
) -> FewShotOut:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is empty")
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")

    # Generate the one-sentence summary server-side so the frontend
    # doesn't have to wait on a second LLM round-trip.
    summary = await summarise_few_shot(req.prompt, req.code)

    row = await fs_store.create_few_shot(
        session,
        prompt=req.prompt,
        code=req.code,
        summary=summary,
        style=req.style,
        source_conversation_id=req.source_conversation_id,
        source_message_id=req.source_message_id,
    )
    return _to_out(row)


@router.get("/few_shots", response_model=list[FewShotOut])
async def list_few_shots(
    style: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[FewShotOut]:
    rows = await fs_store.list_few_shots(session, style=style, limit=limit)
    return [_to_out(r) for r in rows]


__all__ = ["router"]
