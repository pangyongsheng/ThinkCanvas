"""Local embedding model wrapper.

Single-user project — no auth, no rate limiting. Loads ``bge-small-zh``
on first call (HuggingFace cache, ~100MB download the first time),
caches in a module-level singleton so we don't reload per request.

Output is a 512-dim float vector. Serialise to JSON when storing in
the few_shots table — we don't bother with pgvector for the current
data scale.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

import numpy as np


logger = logging.getLogger("thinkcanvas.embeddings")

_MODEL_NAME = "BAAI/bge-small-zh"

# bge-* models want this prefix on queries (not on documents). Keeps
# the official retrieval score; without it, semantic search quality
# drops noticeably.
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


@lru_cache(maxsize=1)
def _get_model():
    """Load the SentenceTransformer model once per process."""
    from sentence_transformers import SentenceTransformer

    logger.info("embeddings.loading model=%s", _MODEL_NAME)
    model = SentenceTransformer(_MODEL_NAME)
    logger.info("embeddings.ready dim=%d", model.get_sentence_embedding_dimension())
    return model


def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """Embed a batch of strings. ``is_query=True`` prepends the bge
    retrieval prefix — only use it for search queries, not when
    embedding documents to be stored.
    """
    if not texts:
        return []
    model = _get_model()
    inputs = (
        [_QUERY_PREFIX + t for t in texts] if is_query else list(texts)
    )
    vectors = model.encode(inputs, normalize_embeddings=True)
    return [v.astype(float).tolist() for v in vectors]


def embed_one(text: str, *, is_query: bool = False) -> list[float]:
    """Convenience wrapper for the common single-text case."""
    return embed_texts([text], is_query=is_query)[0]


async def embed_one_async(text: str, *, is_query: bool = False) -> list[float]:
    """Async wrapper around ``embed_one``.

    The model encode is CPU-bound; we run it in ``run_in_executor`` so
    the event loop isn't blocked while a large request batch is being
    embedded. Use this from async HTTP handlers / background tasks.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: embed_one(text, is_query=is_query)
    )


def encode_json(vector: list[float]) -> str:
    """Serialise a vector to compact JSON for DB storage."""
    return json.dumps(vector, ensure_ascii=False)


def decode_json(blob: str | None) -> list[float] | None:
    """Inverse of ``encode_json``. Returns ``None`` for ``None``/empty."""
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        logger.warning("embeddings.decode_json.bad_input len=%d", len(blob))
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity assuming vectors are already L2-normalised
    (``normalize_embeddings=True`` on encode). Falls back to a
    re-normalised dot product for unnormalised inputs.
    """
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


__all__ = [
    "embed_texts",
    "embed_one",
    "embed_one_async",
    "encode_json",
    "decode_json",
    "cosine_similarity",
]
