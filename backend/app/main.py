"""FastAPI application entry point."""
import os
import sys
from pathlib import Path as _Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware.user_id import UserIdMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.readyz import router as readyz_router
from app.api.v1.render import router as render_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.few_shots import router as few_shots_router
from app.config import get_settings, project_root
from app.core.logging import configure_logging, install_fastapi_exception_logger

# Load .env explicitly so process-level os.environ is populated for any
# third-party client that doesn't go through pydantic-settings (e.g. litellm).
load_dotenv(project_root / ".env", override=False)


def _augment_path_with_tex_bin() -> None:
    """Make sure Manim subprocesses can find a LaTeX executable.

    Manim uses ``MathTex`` / ``Tex`` which shell out to ``latex``. On
    macOS, MacTeX installs to ``/Library/TeX/texbin`` which is **not**
    in the conda env's ``PATH``, so the subprocess spawned by the
    FastAPI process can't find it and crashes with
    ``FileNotFoundError: 'latex'``. Probe the canonical paths and
    prepend whichever exists; on Linux the user is expected to install
    ``texlive-latex-extra`` which puts ``latex`` on the default PATH
    already.
    """
    if sys.platform != "darwin":
        return
    candidates = (
        _Path("/Library/TeX/texbin"),
        _Path("/opt/homebrew/opt/texlive/bin"),
        _Path("/usr/local/opt/texlive/bin"),
    )
    found = next((p for p in candidates if p.exists()), None)
    if found is None:
        return
    current = os.environ.get("PATH", "")
    tex_bin = str(found)
    if tex_bin not in current.split(":"):
        os.environ["PATH"] = f"{tex_bin}:{current}" if current else tex_bin


_augment_path_with_tex_bin()

# Configure logging BEFORE creating the app so middleware captures everything.
configure_logging(level="INFO")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    install_fastapi_exception_logger(app)

    # CORS — frontend at :3000 talks to backend at :8000
    cors_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    # Stamp request.state.user_id from the X-User-Id header.
    # Goes AFTER CORS so OPTIONS preflights (which carry no body) still
    # get a CORS response, but the middleware itself is cheap so order
    # doesn't matter functionally.
    app.add_middleware(UserIdMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(readyz_router, prefix=settings.api_v1_prefix)
    app.include_router(generate_router, prefix=settings.api_v1_prefix)
    app.include_router(render_router, prefix=settings.api_v1_prefix)
    app.include_router(tasks_router, prefix=settings.api_v1_prefix)
    app.include_router(conversations_router, prefix=settings.api_v1_prefix)
    app.include_router(few_shots_router, prefix=settings.api_v1_prefix)

    # Static: serve generated videos
    media_dir = project_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()
