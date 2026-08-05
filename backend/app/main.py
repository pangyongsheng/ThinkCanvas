"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.readyz import router as readyz_router
from app.api.v1.render import router as render_router
from app.config import get_settings, project_root


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    # CORS — frontend at :3000 talks to backend at :8000
    cors_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
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

    # Static: serve generated videos
    media_dir = project_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()
