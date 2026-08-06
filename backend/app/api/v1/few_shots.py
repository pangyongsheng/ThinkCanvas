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
import asyncio
import logging

from app.agents.summarizer import summarise_few_shot
from app.db.models import FewShot
from app.db.session import async_session_factory
from app.services.embeddings import (
    cosine_similarity,
    decode_json,
    embed_one,
    embed_one_async,
    encode_json,
)
from app.storage import few_shots as fs_store


router = APIRouter(tags=["few_shots"])
logger = logging.getLogger("thinkcanvas.api.few_shots")


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

    # Generate the summary synchronously (LLM call, ~2s) so the
    # response carries a useful summary back to the UI. Embedding is
    # computed in the background so the POST round-trip doesn't have
    # to wait for the local model.
    summary = await summarise_few_shot(req.prompt, req.code)

    row = await fs_store.create_few_shot(
        session,
        prompt=req.prompt,
        code=req.code,
        summary=summary,
        style=req.style,
        source_conversation_id=req.source_conversation_id,
        source_message_id=req.source_message_id,
        summary_embedding_json=None,  # filled in by background task
    )

    # Fire-and-forget: compute the embedding after we've returned to
    # the client. The task uses its own DB session because the request
    # session will close as soon as this handler returns.
    asyncio.create_task(
        _backfill_embedding(few_shot_id=row.id, summary=summary)
    )

    return _to_out(row)


async def _backfill_embedding(*, few_shot_id: str, summary: str) -> None:
    """Compute the summary embedding and update the row in-place.

    Runs after the HTTP response has been sent. Errors are logged but
    not raised — the row stays valid (search just won't find it until
    the embedding lands).
    """
    try:
        vec = await embed_one_async(summary)
    except Exception:
        logger.exception(
            "few_shots.backfill.embed_failed id=%s", few_shot_id
        )
        return

    blob = encode_json(vec)
    try:
        async with async_session_factory() as session:
            row = await session.get(FewShot, few_shot_id)
            if row is None:
                logger.warning(
                    "few_shots.backfill.row_missing id=%s", few_shot_id
                )
                return
            row.summary_embedding = blob
            await session.commit()
        logger.info(
            "few_shots.backfill.done id=%s dim=%d", few_shot_id, len(vec)
        )
    except Exception:
        logger.exception(
            "few_shots.backfill.update_failed id=%s", few_shot_id
        )


@router.get("/few_shots", response_model=list[FewShotOut])
async def list_few_shots(
    q: Optional[str] = None,
    style: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[FewShotOut]:
    """List curated examples.

    Without ``q``: most recent first (up to ``limit``).
    With ``q``: ranked by semantic similarity to ``q`` (top-``limit``).
    """
    if q is not None and q.strip():
        rows = await _search_by_similarity(
            session, q=q.strip(), style=style, limit=limit
        )
    else:
        rows = await fs_store.list_few_shots(session, style=style, limit=limit)
    return [_to_out(r) for r in rows]


async def _search_by_similarity(
    session: AsyncSession,
    *,
    q: str,
    style: Optional[str],
    limit: int,
) -> list[FewShot]:
    """Rank stored few_shots by cosine similarity of ``summary_embedding``
    to the embedding of ``q``. Rows without an embedding are skipped.
    """
    query_vec = embed_one(q, is_query=True)
    rows = await fs_store.list_few_shots(session, style=style, limit=200)

    scored: list[tuple[float, FewShot]] = []
    for row in rows:
        vec = decode_json(row.summary_embedding)
        if vec is None:
            continue
        score = cosine_similarity(query_vec, vec)
        scored.append((score, row))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [row for _, row in scored[:limit]]


__all__ = ["router"]
