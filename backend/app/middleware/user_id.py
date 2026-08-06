"""Read ``X-User-Id`` from every request and stamp it on ``request.state``.

Identity is a client-side ULID (no auth). The header value is trusted
as-is — there is no signing, because the system has no concept of a
private resource to protect.

If the header is missing or malformed we fall back to the hard-coded
anonymous ULID so the request still resolves to a real owner row.
"""
from __future__ import annotations

import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.db.models import ANON_USER_ID


logger = logging.getLogger("thinkcanvas.middleware.user_id")

# ULIDs are 26 chars of Crockford base32 (case-insensitive). Tight
# validation so we don't trust arbitrary header input.
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-Z]{26}$", re.IGNORECASE)


def _coerce_user_id(raw):
    """Validate and normalize a header value into a canonical uppercase ULID.

    Returns ``ANON_USER_ID`` if the value is missing or malformed.
    """
    if raw and _ULID_RE.match(raw):
        return raw.upper()
    return ANON_USER_ID


class UserIdMiddleware(BaseHTTPMiddleware):
    """Stamp ``request.state.user_id`` on every request."""

    async def dispatch(self, request, call_next):
        request.state.user_id = _coerce_user_id(
            request.headers.get("x-user-id")
        )
        request.state.user_id_source = (
            "header" if request.state.user_id != ANON_USER_ID else "anon"
        )
        response = await call_next(request)
        return response


__all__ = ["UserIdMiddleware", "_coerce_user_id"]
