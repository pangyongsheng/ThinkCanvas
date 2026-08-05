"""HTTP routes for the generate pipeline.

This file is intentionally thin: it converts HTTP requests to CoderAgent calls
(or to a one-shot retry loop for the legacy sync endpoint) and serializes the
result. All business logic — ReAct loop, tool execution, observation feed-back —
lives in :mod:`app.agents.coder`.

Endpoints
    - POST /generate          synchronous; validate-only retry; no render
    - GET  /generate/stream   SSE; same as /generate but streams progress
    - POST /generate/agent    uses :class:`CoderAgent`; validates + renders with
                               feed-back retry; recommended entry point
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.coder import (
    _build_user_message,
    _call_llm_react,
    _PROMPT_PATH,
)
from app.agents.react_coder import build_agent as build_langgraph_react_agent
from app.agents.react_coder import run as run_langgraph_react
from app.api.v1.render import to_video_url
from app.config import get_settings
from app.llm.client import get_llm
from app.renderers.manim import render_code
from app.tools.validator import extract_scene_name, validate_code

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


# ---------------------------------------------------------------------------
# Legacy /generate + /generate/stream: validate-only retry (no render)
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> str:
    """Format one SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_simple_retry(
    prompt: str,
    llm,
    system_prompt: str,
    max_retries: int,
    on_event=None,
) -> tuple[str | None, list[dict]]:
    """Validate-only retry loop. Used by ``/generate`` and ``/generate/stream``."""
    history: list[dict] = []

    for attempt in range(max_retries + 1):
        prev_error = history[-1]["error"] if history else None
        user_msg = _build_user_message(prompt, prev_error)

        if on_event:
            await on_event("llm_call", {"step": "generating", "attempt": attempt + 1})

        result = await _call_llm_react(llm, system_prompt, user_msg)
        if result is None:
            history.append({"attempt": attempt + 1, "code": None, "error": "LLM call failed"})
            if on_event:
                await on_event("retry", {"reason": "llm_error", "attempt": attempt + 1})
            continue

        code = result["code"]

        if on_event:
            await on_event("validating", {"attempt": attempt + 1})

        ok, error = validate_code(code)
        if ok:
            history.append({"attempt": attempt + 1, "code": code, "thought": result["thought"], "error": None})
            return code, history

        history.append({"attempt": attempt + 1, "code": code, "thought": result["thought"], "error": error})
        if on_event:
            await on_event("retry", {"reason": "validation_failed", "attempt": attempt + 1, "error": error})

    return None, history


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """Synchronous; validates only (legacy). Use ``/generate/agent`` to also render."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    settings = get_settings()
    code, history = await _run_simple_retry(
        prompt=prompt,
        llm=get_llm(),
        system_prompt=_load_system_prompt(),
        max_retries=settings.llm_max_retries,
    )

    if code is None:
        raise HTTPException(
            status_code=422,
            detail={"error": f"failed after {len(history)} attempts", "history": history},
        )

    return GenerateResponse(
        prompt=prompt,
        code=code,
        scene_name=extract_scene_name(code),
        model=get_llm().model_name,
        attempts=len(history),
        thoughts=[h.get("thought") or "" for h in history],
    )


async def _run_pipeline_streaming(
    prompt: str,
    llm,
    system_prompt: str,
    max_retries: int,
) -> AsyncIterator[tuple[str, dict]]:
    """Same as /generate but yields progress events for SSE consumption."""
    queue: list[tuple[str, dict]] = []

    async def push(name: str, data: dict) -> None:
        queue.append((name, data))

    code, history = await _run_simple_retry(
        prompt=prompt,
        llm=llm,
        system_prompt=system_prompt,
        max_retries=max_retries,
        on_event=push,
    )

    for name, data in queue:
        yield name, data

    if code is None:
        yield "failed", {"error": f"failed after {len(history)} attempts", "history": history}
        return

    scene_name = extract_scene_name(code)
    yield "code", {
        "code": code,
        "scene_name": scene_name,
        "attempts": len(history),
    }

    yield "rendering", {"scene_name": scene_name}
    result = await render_code(code, scene_name)

    if result.error or not result.video_path:
        yield "failed", {"error": result.error or "render failed", "history": history}
        return

    yield "done", {
        "code": code,
        "scene_name": scene_name,
        "video_url": to_video_url(result.video_path),
        "attempts": len(history),
        "duration_sec": result.duration_sec,
        "thoughts": [h.get("thought") or "" for h in history],
    }


@router.get("/generate/stream")
async def generate_stream(prompt: str) -> StreamingResponse:
    """SSE stream: simple validate-only retry + manual render at the end."""
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is empty")

    settings = get_settings()
    llm = get_llm()

    async def event_generator():
        try:
            async for event_name, data in _run_pipeline_streaming(
                prompt=prompt.strip(),
                llm=llm,
                system_prompt=_load_system_prompt(),
                max_retries=settings.llm_max_retries,
            ):
                yield _sse(event_name, data)
        except Exception as e:
            yield _sse("failed", {"error": f"server error: {type(e).__name__}: {e}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# /generate/agent: delegates to the CoderAgent class.
# ---------------------------------------------------------------------------


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


@router.post("/generate/agent", response_model=GenerateResponse)
async def generate_agent(req: GenerateRequest) -> GenerateResponse:
    """LangGraph ReAct agent entry point.

    Uses ``langgraph.prebuilt.create_react_agent`` (the canonical LangChain
    agent pattern) with our two ``@tool``s. The LLM picks when to call
    ``validate_manim_code`` and ``render_manim_dryrun``; render errors
    flow back as ``ToolMessage`` and the agent self-corrects.
    """
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    agent = build_langgraph_react_agent(get_llm(), max_iterations=6)
    result = await run_langgraph_react(agent, prompt, max_iterations=6)

    if result["code"] is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "agent failed after max iterations",
                "tool_log": result["tool_log"],
            },
        )

    return GenerateResponse(
        prompt=prompt,
        code=result["code"],
        scene_name=extract_scene_name(result["code"]),
        model=get_llm().model_name,
        attempts=len(result["tool_log"]),
        thoughts=[entry.get("result", "") for entry in result["tool_log"]],
    )
