"""Tests for the local embedding service.

The model itself isn't loaded — we test the JSON encode/decode +
cosine math, which are the parts that matter for correctness without
needing a network download.
"""
from __future__ import annotations

import math

from app.services.embeddings import (
    cosine_similarity,
    decode_json,
    encode_json,
)


def test_encode_decode_roundtrip():
    vec = [0.1, 0.2, 0.3, -0.4]
    blob = encode_json(vec)
    assert decode_json(blob) == vec


def test_decode_returns_none_for_empty_inputs():
    assert decode_json(None) is None
    assert decode_json("") is None


def test_decode_returns_none_for_malformed_input():
    # Bad JSON shouldn't crash the request - it should be silently skipped.
    assert decode_json("{not valid json") is None


def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 0.0, 0.0]
    assert math.isclose(cosine_similarity(v, v), 1.0, abs_tol=1e-6)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert math.isclose(cosine_similarity(a, b), 0.0, abs_tol=1e-6)


def test_cosine_similarity_opposite_vectors_is_minus_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert math.isclose(cosine_similarity(a, b), -1.0, abs_tol=1e-6)


def test_cosine_similarity_zero_vector_returns_zero():
    # Avoid divide-by-zero; we want a defined 0.0 score instead of NaN.
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_ranking():
    """The 'close' vector should outrank the 'far' one."""
    base = [1.0, 1.0, 0.0]
    close = [1.0, 1.0, 0.1]
    far = [-1.0, -1.0, 0.0]
    assert cosine_similarity(base, close) > cosine_similarity(base, far)
