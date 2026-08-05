"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.readyz import router as readyz_router
from app.api.v1.render import router as render_router
from app.config import get_settings, project_root


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(readyz_router, prefix=settings.api_v1_prefix)
    app.include_router(generate_router, prefix=settings.api_v1_prefix)
    app.include_router(render_router, prefix=settings.api_v1_prefix)

    # Serve generated videos
    media_dir = project_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()
