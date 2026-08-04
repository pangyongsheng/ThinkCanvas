"""FastAPI application entry point."""
from fastapi import FastAPI

from app.api.v1.health import router as health_router
from app.api.v1.readyz import router as readyz_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(readyz_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
