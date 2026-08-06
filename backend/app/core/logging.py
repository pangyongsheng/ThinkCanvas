"""Centralised logging + exception capture for the backend.

Three layers:

1. ``configure_logging()`` — call once at startup. Wires the root logger to
   stream to stderr (uvicorn captures it) with a uniform format.

2. ``log_exception()`` — drop-in replacement for bare ``logger.exception``
   that also dumps the exception type + first frame of the traceback as a
   single-line summary, easy to grep in uvicorn logs.

3. ``capture_route_errors()`` — FastAPI middleware that catches anything
   escaping a route and logs it before FastAPI's default 500 handler.
   This makes stream/SSE failures (which FastAPI sometimes swallows) visible.
"""
from __future__ import annotations

import logging
import sys
import traceback
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib logging + structlog once at app boot."""
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def log_exception(logger: logging.Logger, msg: str, **extra: Any) -> None:
    """Log ``msg`` + the current exception (must be inside an ``except``).

    Emits two records: the human-readable message with the exception type
    and a one-line summary of the deepest frame, plus the full traceback.
    Both are written to stderr so uvicorn captures them.
    """
    exc_type, exc_value, tb = sys.exc_info()
    if exc_type is None:
        logger.error("%s (no active exception)", msg, extra=extra)
        return

    # Pick the deepest application frame (skip stdlib / third-party noise)
    deepest = None
    for frame in traceback.extract_tb(tb):
        if "/site-packages/" not in frame.filename and "/lib/python" not in frame.filename:
            deepest = frame

    summary = f"{exc_type.__name__}: {exc_value}"
    if deepest:
        summary += f" @ {deepest.filename.split('/')[-1]}:{deepest.lineno} in {deepest.name}"

    logger.error("%s | %s", msg, summary, extra=extra)
    logger.error("Full traceback:\n%s", "".join(traceback.format_exception(exc_type, exc_value, tb)))


def install_fastapi_exception_logger(app) -> None:
    """Install middleware that logs any exception escaping a route.

    Without this, errors inside ``StreamingResponse`` generators or
    background tasks vanish into the void — uvicorn just logs a 200.
    """
    import starlette.middleware.base
    from starlette.requests import Request

    logger = logging.getLogger("thinkcanvas.route")

    class _ErrorLoggingMiddleware(starlette.middleware.base.BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            try:
                return await call_next(request)
            except Exception as exc:  # noqa: BLE001
                log_exception(
                    logger,
                    f"Unhandled error in {request.method} {request.url.path}",
                    path=request.url.path,
                    method=request.method,
                )
                raise

    app.add_middleware(_ErrorLoggingMiddleware)
