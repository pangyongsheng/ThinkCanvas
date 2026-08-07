"""Tests for ``app.agents.retriever``.

Strategy: mock both the embedding model and ``list_few_shots`` so the
test runs without ``aiosqlite`` / bge-small-zh. The retriever's job
is "score + sort"; we trust SQLAlchemy's select to work.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.retriever import retrieve_similar_summaries


def _make_row(id_: str, summary: str, style: str, embedding_blob: str | None):
    """A real FewShot ORM row is awkward to construct in a unit test;
    use a MagicMock with the attributes the retriever reads.
    """
    row = MagicMock()
    row.id = id_
    row.summary = summary
    row.style = style
    row.summary_embedding = embedding_blob
    return row


@pytest.mark.asyncio
async def test_returns_top_k_by_similarity():
    rows = [
        _make_row("a", "冒泡排序", "3b1b", "[1,0,0]"),
        _make_row("b", "二分查找", "3b1b", "[0,1,0]"),
    ]

    async def fake_embed(text, *, is_query=False):
        return [1.0, 0.0, 0.0]  # identical to row 'a' → highest score

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", return_value=rows):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="3b1b", top_k=2,
        )

    assert [r.summary for r in result] == ["冒泡排序", "二分查找"]


@pytest.mark.asyncio
async def test_filters_by_style_in_fallback():
    """When embedding fails, we delegate to list_few_shots which itself
    filters by style. We just need to verify the retriever passes style
    through.
    """
    captured = {}

    async def fake_list(session, *, style=None, limit=50):
        captured["style"] = style
        captured["limit"] = limit
        return []

    async def fake_embed(text, *, is_query=False):
        raise RuntimeError("model down")

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", side_effect=fake_list):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="academic", top_k=2,
        )

    assert captured["style"] == "academic"
    assert captured["limit"] == 2
    assert result == []


@pytest.mark.asyncio
async def test_skips_rows_without_embedding():
    rows = [
        _make_row("a", "has-emb", "3b1b", "[1,0,0]"),
        _make_row("b", "no-emb", "3b1b", None),
    ]

    async def fake_embed(text, *, is_query=False):
        return [1.0, 0.0, 0.0]

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", return_value=rows):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="3b1b",
        )

    assert [r.summary for r in result] == ["has-emb"]


@pytest.mark.asyncio
async def test_skips_rows_with_invalid_json_embedding():
    rows = [
        _make_row("a", "good", "3b1b", "[1,0,0]"),
        _make_row("b", "bad-json", "3b1b", "not-a-json-list"),
    ]

    async def fake_embed(text, *, is_query=False):
        return [1.0, 0.0, 0.0]

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", return_value=rows):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="3b1b",
        )

    assert [r.summary for r in result] == ["good"]


@pytest.mark.asyncio
async def test_falls_back_to_recency_when_embed_fails():
    rows = [_make_row(f"r{i}", f"s{i}", "3b1b", "[1,0,0]") for i in range(3)]

    async def fake_embed(text, *, is_query=False):
        raise RuntimeError("model down")

    async def fake_list(session, *, style=None, limit=50):
        return rows[:limit]

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", side_effect=fake_list):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="3b1b", top_k=2,
        )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_empty_prompt_returns_empty():
    result = await retrieve_similar_summaries(
        MagicMock(), prompt="   ", style="3b1b",
    )
    assert result == []


@pytest.mark.asyncio
async def test_respects_top_k():
    rows = [
        _make_row(f"r{i}", f"s{i}", "3b1b", "[1,0,0]")  # all identical scores
        for i in range(5)
    ]

    async def fake_embed(text, *, is_query=False):
        return [1.0, 0.0, 0.0]

    with patch("app.agents.retriever.embed_one_async", side_effect=fake_embed), \
         patch("app.agents.retriever.list_few_shots", return_value=rows):
        result = await retrieve_similar_summaries(
            MagicMock(), prompt="x", style="3b1b", top_k=3,
        )

    assert len(result) == 3
