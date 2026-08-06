"""Tests for the backfill-embedding background task."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.db.models import Conversation, FewShot
from app.api.v1 import few_shots as fs_api


def _seed_row(s, *, row_id="fs1", summary="hello world"):
    s.add(Conversation(id="c1", title="t", style="3b1b", user_id="u1"))
    s.add(FewShot(
        id=row_id,
        prompt="冒泡排序",
        code="from manim import *\nclass Foo(Scene): pass",
        summary=summary,
        style="3b1b",
        source_conversation_id="c1",
    ))
    s.commit()
    return row_id


@pytest.mark.asyncio
async def test_backfill_writes_embedding_to_db():
    """Backfill writes the embedding into the row.

    The helper opens its own async session; we replace both
    ``embed_one_async`` and ``async_session_factory`` with fakes so
    the test doesn't need a real async DB engine.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    fake_vec = [0.1] * 512
    fake_row = AsyncMock()
    fake_row.summary_embedding = None  # initial value

    async def _embed(text, *, is_query=False):
        return fake_vec

    async def _commit():
        pass

    fake_session = AsyncMock()
    fake_session.get = AsyncMock(return_value=fake_row)
    fake_session.commit = AsyncMock(side_effect=_commit)

    @asynccontextmanager
    async def _fake_factory():
        yield fake_session

    with patch.object(fs_api, "embed_one_async", side_effect=_embed), \
         patch.object(fs_api, "async_session_factory", _fake_factory):
        await fs_api._backfill_embedding(few_shot_id="fs1", summary="hello")

    # The helper should have set summary_embedding to a JSON-encoded vec.
    assert fake_row.summary_embedding is not None
    decoded = json.loads(fake_row.summary_embedding)
    assert decoded == fake_vec
    fake_session.get.assert_awaited_once_with(FewShot, "fs1")
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_skips_missing_row_gracefully():
    """Missing row: log warning, no commit."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    async def _embed(text, *, is_query=False):
        return [0.0] * 512

    fake_session = AsyncMock()
    fake_session.get = AsyncMock(return_value=None)  # row gone
    fake_session.commit = AsyncMock()

    @asynccontextmanager
    async def _fake_factory():
        yield fake_session

    with patch.object(fs_api, "embed_one_async", side_effect=_embed), \
         patch.object(fs_api, "async_session_factory", _fake_factory):
        await fs_api._backfill_embedding(few_shot_id="nope", summary="x")

    # Commit must NOT have been called when the row is missing.
    fake_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_swallows_embed_errors():
    """Model failure: log exception, no DB touch."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    async def _boom(text, *, is_query=False):
        raise RuntimeError("model crashed")

    fake_session = AsyncMock()

    @asynccontextmanager
    async def _fake_factory():
        yield fake_session

    with patch.object(fs_api, "embed_one_async", side_effect=_boom), \
         patch.object(fs_api, "async_session_factory", _fake_factory):
        # Must not raise.
        await fs_api._backfill_embedding(few_shot_id="fs_err", summary="x")

    # Session was never opened (the embed call failed first).
    fake_session.get.assert_not_called()
    fake_session.commit.assert_not_called()
