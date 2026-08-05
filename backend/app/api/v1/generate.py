"""Generate endpoint: text prompt -> LLM -> validated Manim code, with retry."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.config import get_settings, project_root
from app.llm.client import get_llm
from app.tools.validator import extract_scene_name, validate_code

router = APIRouter(tags=["generate"])


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    prompt: str
    code: str
    scene_name: str | None
    model: str
    attempts: int  # how many tries it took (1 = first try)


_PROMPT_PATH = project_root / "shared" / "prompts" / "system" / "v1.txt"
_THINK_BLOCK = re.compile(
    r"<\s*\w*think\w*>\s*.*?\s*<\s*/\s*\w*think\w*>",
    re.DOTALL,
)


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _clean_code(text: str) -> str:
    """Strip 思考块 and markdown code fences."""
    text = _THINK_BLOCK.sub("", text).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _build_user_message(prompt: str, prev_error: str | None) -> str:
    """Compose the user msg; on retry, append the previous error for self-correction."""
    if prev_error is None:
        return prompt
    return (
        f"{prompt}\n\n"
        f"---\n"
        f"你上一次的输出有问题：\n{prev_error}\n\n"
        f"请修正后重新输出完整代码。\n"
    )


async def _generate_with_retry(
    prompt: str,
    llm,
    system_prompt: str,
    max_retries: int,
) -> tuple[str | None, list[dict]]:
    """Returns (validated_code or None, attempt_history).

    history entries: ``{attempt, code, error}``.
    """
    history: list[dict] = []

    for attempt in range(max_retries + 1):
        prev_error = history[-1]["error"] if history else None
        user_msg = _build_user_message(prompt, prev_error)

        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
        raw = response.content if isinstance(response.content, str) else str(response.content)
        code = _clean_code(raw)
        ok, error = validate_code(code)

        if ok:
            return code, history

        history.append({"attempt": attempt + 1, "code": code, "error": error})

    return None, history


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    settings = get_settings()
    llm = get_llm()

    code, history = await _generate_with_retry(
        prompt=prompt,
        llm=llm,
        system_prompt=_load_system_prompt(),
        max_retries=settings.llm_max_retries,
    )

    if code is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"failed after {len(history)} attempts",
                "history": history,
            },
        )

    return GenerateResponse(
        prompt=prompt,
        code=code,
        scene_name=extract_scene_name(code),
        model=llm.model_name,
        attempts=len(history) + 1,
    )
