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

import logging

from fastapi import APIRouter, HTTPException
from fastapi import Query
from pydantic import BaseModel

from app.agents.react_coder import run_agent
from app.agents.styles import DEFAULT_STYLE_ID, STYLE_IDS
from app.config import get_settings
from app.core.logging import log_exception
from app.renderers.manim import render_code
from app.tools.validator import extract_scene_name

router = APIRouter(tags=["generate"])

logger = logging.getLogger("thinkcanvas.api")


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
async def generate_stream(
    prompt: str,
    style: str = Query(DEFAULT_STYLE_ID),
):
    """SSE stream. Delegates to the standard agent then renders.

    Emits one ``code`` event (when the agent finishes), one ``rendering``
    event, then ``done`` with the video URL or ``failed``.
    """
    from fastapi.responses import StreamingResponse
    from app.api.v1.render import to_video_url

    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is empty")
    if style not in STYLE_IDS:
        raise HTTPException(status_code=400, detail=f"unknown style: {style}")

    async def event_generator():
        import json as _json
        import asyncio

        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

        from app.db.session import async_session_factory
        from app.storage import conversations as conv_store
        from app.storage import tasks as task_store

        # Step 5: persist every request so /tasks history survives reload.
        async with async_session_factory() as session:
            task = await task_store.create_task(session, prompt=prompt.strip(), style=style)
            task_id = task.id

        try:
            yield _sse("started", {"prompt": prompt, "task_id": task_id})

            result = await run_agent(prompt.strip(), style_id=style, max_iterations=8)
            tool_log = result.get("tool_log", [])
            tool_steps = result.get("tool_steps", [])
            tool_calls = len(tool_log)
            code = result.get("code")

            if not code:
                msgs = result.get("messages", [])
                last_msg = str(msgs[-1])[:400] if msgs else ""
                async with async_session_factory() as session:
                    await task_store.update_task(
                        session,
                        task_id,
                        status="failed",
                        error="agent failed to produce code",
                        tool_calls=tool_calls,
                    )
                    await conv_store.write_agent_steps(
                        session, task_id=task_id, steps=tool_steps,
                    )
                yield _sse(
                    "failed",
                    {
                        "error": "agent failed to produce code",
                        "task_id": task_id,
                        "tool_calls": tool_calls,
                        "iterations": len(msgs),
                        "last_message": last_msg,
                    },
                )
                return

            scene_name = extract_scene_name(code)
            yield _sse("code", {"code": code, "scene_name": scene_name, "task_id": task_id})
            yield _sse("rendering", {"scene_name": scene_name})

            render_result = await render_code(code, scene_name)
            if render_result.error or not render_result.video_path:
                async with async_session_factory() as session:
                    await task_store.update_task(
                        session,
                        task_id,
                        status="failed",
                        code=code,
                        scene_name=scene_name,
                        error=render_result.error or "no video",
                        duration_sec=render_result.duration_sec,
                        tool_calls=tool_calls,
                    )
                    await conv_store.write_agent_steps(
                        session, task_id=task_id, steps=tool_steps,
                    )
                yield _sse(
                    "failed",
                    {"error": render_result.error or "render failed", "task_id": task_id},
                )
                return

            video_url = to_video_url(render_result.video_path)
            async with async_session_factory() as session:
                await task_store.update_task(
                    session,
                    task_id,
                    status="succeeded",
                    code=code,
                    scene_name=scene_name,
                    video_url=video_url,
                    duration_sec=render_result.duration_sec,
                    tool_calls=tool_calls,
                    clear_error=True,
                )
                await conv_store.write_agent_steps(
                    session, task_id=task_id, steps=tool_steps,
                )
            yield _sse(
                "done",
                {
                    "code": code,
                    "scene_name": scene_name,
                    "video_url": video_url,
                    "duration_sec": render_result.duration_sec,
                    "task_id": task_id,
                },
            )
        except Exception:  # noqa: BLE001
            log_exception(logger, "generate/stream unhandled error", prompt=prompt[:80])
            try:
                async with async_session_factory() as session:
                    await task_store.update_task(
                        session,
                        task_id,
                        status="failed",
                        error="internal server error",
                    )
            except Exception:
                log_exception(logger, "failed to write task error state")
            yield _sse(
                "failed",
                {"error": "internal server error (see backend logs)", "task_id": task_id},
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["router", "GenerateRequest", "GenerateResponse"]
