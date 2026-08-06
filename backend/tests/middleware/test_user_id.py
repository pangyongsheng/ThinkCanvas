"""Tests for the X-User-Id middleware and ULID coercion.

The middleware has no async DB work - it just stamps ``request.state``.
These tests cover the regex + the BaseHTTPMiddleware dispatch path.
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app.db.models import ANON_USER_ID
from app.middleware.user_id import UserIdMiddleware, _coerce_user_id


def test_coerce_accepts_valid_ulid():
    raw = "01HZX9C5K3PVBX8Q4M0W2N6R7T"
    assert _coerce_user_id(raw) == raw


def test_coerce_lowercases_then_uppercases():
    # Crockford base32 is case-insensitive on input.
    assert _coerce_user_id("01hzx9c5k3pvbx8q4m0w2n6r7t") == "01HZX9C5K3PVBX8Q4M0W2N6R7T"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-ulid",
        "01HZX9C5K3PVBX8Q4M0W2N6R",  # 25 chars
        "01HZX9C5K3PVBX8Q4M0W2N6R7TT",  # 27 chars
        "01HZX9C5K3PVBX8Q4M0W2N6R7!",
        "01HZX9C5K3PVBX8Q4M0W2N6R7I",  # I excluded
    ],
)
def test_coerce_falls_back_to_anon_on_invalid(bad):
    assert _coerce_user_id(bad) == ANON_USER_ID


def test_coerce_falls_back_to_anon_on_none():
    assert _coerce_user_id(None) == ANON_USER_ID


@pytest.mark.asyncio
async def test_middleware_stamps_state_for_valid_header():
    """Valid X-User-Id header stamps request.state.user_id."""
    seen = {}

    async def _downstream(scope, receive, send):
        req = Request(scope)
        seen["user_id"] = req.state.user_id
        seen["source"] = req.state.user_id_source
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_msg):
        return None

    mw = UserIdMiddleware(_downstream)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(b"x-user-id", b"01HZX9C5K3PVBX8Q4M0W2N6R7T")],
    }
    await mw(scope, _receive, _send)
    assert seen["user_id"] == "01HZX9C5K3PVBX8Q4M0W2N6R7T"
    assert seen["source"] == "header"


@pytest.mark.asyncio
async def test_middleware_uses_anon_when_header_missing():
    captured = {}

    async def _downstream(scope, receive, send):
        req = Request(scope)
        captured["user_id"] = req.state.user_id
        captured["source"] = req.state.user_id_source
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_msg):
        return None

    mw = UserIdMiddleware(_downstream)
    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    await mw(scope, _receive, _send)
    assert captured["user_id"] == ANON_USER_ID
    assert captured["source"] == "anon"
