"""HTTP routes for the generate pipeline.

Thin layer: receives requests, delegates to the canonical LangChain agent
(see ``app.agents.builder`` and ``app.agents.react_coder``). No LLM /
prompt / retry logic lives here.

Endpoints
    - POST /generate          validate-only (no render)
    - GET  /generate/stream   SSE; validates + renders with progress
    - POST /generate/agent    full ReAct agent (validate + render + retry)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.react_coder import run_agent
from app.config import get_settings
from app.renderers.manim import render_code
from app.tools.validator import extract_scene_name

router = APIRouter(tags=["generate"])


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    prompt: str
    code: str
    scene_name: str | None
    model: str
    attempts: int
    thoughts: list[str] = []


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """Validate-only generation (no render)."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    # The agent may decide not to render; for the validate-only endpoint we
    # only need its structured code output.
    result = await run_agent(prompt, max_iterations=4)
    code = result.get("code")
    if not code:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "agent failed to produce valid code",
                "tool_log": result.get("tool_log", []),
            },
        )

    return GenerateResponse(
        prompt=prompt,
        code=code,
        scene_name=extract_scene_name(code),
        model=get_settings().llm_model_raw,
        attempts=len(result.get("tool_log", [])),
        thoughts=[m for m in result.get("messages", []) if m],
    )


@router.post("/generate/agent", response_model=GenerateResponse)
async def generate_agent(req: GenerateRequest) -> GenerateResponse:
    """Full ReAct agent: validate + render + self-correction."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    result = await run_agent(prompt, max_iterations=6)
    code = result.get("code")

    if code is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "agent failed after max iterations",
                "tool_log": result.get("tool_log", []),
            },
        )

    return GenerateResponse(
        prompt=prompt,
        code=code,
        scene_name=extract_scene_name(code),
        model=get_settings().llm_model_raw,
        attempts=len(result.get("tool_log", [])),
        thoughts=[entry.get("result", "") for entry in result.get("tool_log", [])],
    )


@router.get("/generate/stream")
async def generate_stream(prompt: str):
    """SSE stream. Delegates to the standard agent then renders.

    Emits one ``code`` event (when the agent finishes), one ``rendering``
    event, then ``done`` with the video URL or ``failed``.
    """
    from fastapi.responses import StreamingResponse
    from app.api.v1.render import to_video_url

    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is empty")

    async def event_generator():
        import json as _json
        import asyncio

        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield _sse("started", {"prompt": prompt})
            result = await run_agent(prompt.strip(), max_iterations=6)
            code = result.get("code")
            if not code:
                yield _sse("failed", {"error": "agent failed to produce code"})
                return

            scene_name = extract_scene_name(code)
            yield _sse("code", {"code": code, "scene_name": scene_name})
            yield _sse("rendering", {"scene_name": scene_name})

            render_result = await render_code(code, scene_name)
            if render_result.error or not render_result.video_path:
                yield _sse("failed", {"error": render_result.error or "render failed"})
                return

            yield _sse(
                "done",
                {
                    "code": code,
                    "scene_name": scene_name,
                    "video_url": to_video_url(render_result.video_path),
                    "duration_sec": render_result.duration_sec,
                },
            )
        except Exception as e:  # noqa: BLE001
            yield _sse("failed", {"error": f"server error: {type(e).__name__}: {e}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router", "GenerateRequest", "GenerateResponse"]
