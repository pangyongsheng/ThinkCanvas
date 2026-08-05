"""Render endpoint: code -> subprocess(manim) -> mp4 URL."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import project_root
from app.renderers.manim import render_code

router = APIRouter(tags=["render"])


class RenderRequest(BaseModel):
    code: str
    scene_name: str | None = None


class RenderResponse(BaseModel):
    code_path: str
    video_url: str | None
    duration_sec: float
    error: str | None


def to_video_url(abs_video_path) -> str:
    """Convert an absolute video path to a full backend URL.

    Frontend runs at :3000, so the browser needs an absolute URL pointing at
    the backend (:8000) where /media is mounted.
    """
    rel = abs_video_path.relative_to(project_root / "media")
    return f"http://localhost:8000/media/{rel.as_posix()}"


@router.post("/render", response_model=RenderResponse)
async def render(req: RenderRequest) -> RenderResponse:
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")

    result = await render_code(req.code, req.scene_name)

    return RenderResponse(
        code_path=str(result.code_path),
        video_url=to_video_url(result.video_path) if result.video_path else None,
        duration_sec=result.duration_sec,
        error=result.error,
    )
