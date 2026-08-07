"""从 ``few_shots`` 表里按 prompt 相似度召回最相关的 few-shot。

工作流：
  1. HTTP 入口拿到用户 prompt，调 ``retrieve_similar_summaries``。
  2. 取出同风格下所有 FewShot（按 style 过滤），用 ``summary_embedding``
     跟 prompt 的 query embedding 算 cosine。
  3. 按相似度倒序，取 top_k。

为什么不上 pgvector：
  - 当前数据规模（低三位数）内存里跑得动，单次比对 < 1ms
  - 未来上千条时换 pgvector，**只改这个文件**，调用方零感知
  - 留接口形状一致

如果 FewShot 的 ``summary_embedding`` 还没生成（None），跳过这条
——它在 backfill 完成之前不能参与召回，但不会让整次调用失败。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FewShot
from app.services.embeddings import (
    cosine_similarity,
    decode_json,
    embed_one_async,
)
from app.storage.few_shots import list_few_shots


logger = logging.getLogger("thinkcanvas.agents.retriever")


# 没向量库的兜底：当 prompt embedding 失败时，直接按"recency + style"
# 返回最新 N 条，比完全没 few-shot 强。
def _fallback_by_recency(
    session: AsyncSession,
    *,
    style: str,
    top_k: int,
) -> list[FewShot]:
    return list_few_shots(session, style=style, limit=top_k)


async def retrieve_similar_summaries(
    session: AsyncSession,
    *,
    prompt: str,
    style: str,
    top_k: int = 2,
) -> list[FewShot]:
    """按 prompt 语义相似度返回同风格下的 top_k FewShot。

    返回顺序：相似度从高到低。

    失败行为（embedding 模型加载失败 / 所有 embedding 都是 None）：
    退化为"按时间倒序取最新 N 条"，保证调用方始终能拿到一些示例，
    不至于让 system prompt 缺这一段。
    """
    if not prompt.strip():
        return []

    try:
        query_vec = await embed_one_async(prompt, is_query=True)
    except Exception:
        logger.warning("retriever.embed_failed — falling back to recency")
        return await _fallback_by_recency(session, style=style, top_k=top_k)

    candidates = await list_few_shots(session, style=style, limit=200)

    scored: list[tuple[float, FewShot]] = []
    for row in candidates:
        vec = decode_json(row.summary_embedding)
        if not vec:
            continue
        score = cosine_similarity(query_vec, vec)
        scored.append((score, row))

    if not scored:
        # 同风格下没有任何已嵌入的 summary — 用最新几条兜底。
        logger.info(
            "retriever.no_embeddings style=%s rows=%d — falling back to recency",
            style, len(candidates),
        )
        return await _fallback_by_recency(session, style=style, top_k=top_k)

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [row for _, row in scored[:top_k]]
    logger.info(
        "retriever.ok style=%s candidates=%d with_emb=%d top_scores=[%s]",
        style,
        len(candidates),
        len(scored),
        ", ".join(f"{s:.3f}" for s, _ in scored[:top_k]),
    )
    return top


__all__ = ["retrieve_similar_summaries"]
