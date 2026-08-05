"""CoderAgent: the brain of ThinkCanvas.

HTTP-independent: any caller (FastAPI route, CLI, scheduler, test) can
``await agent.run(prompt)`` and get a final Manim code (or None + steps).

Why this lives in `app/agents/` and not inside the FastAPI route:
    - testable in isolation, no HTTP plumbing needed
    - reusable from non-web entry points
    - the routing layer stays HTTP-only

ReAct pattern
    - LLM is the **Action**: writes ``{thought, code}`` JSON.
    - The agent itself runs the **Tools** (validate, render).
    - Tool output (manim stderr) becomes the **Observation** fed back into
      the next user message so the LLM's next attempt has full context.

Why the LLM doesn't call tools directly
    - ``bind_tools()`` requires provider support for OpenAI-style tool_choice
    - MiniMax (and many open-weights clones) don't reliably support it
    - So we let the LLM do one thing (write code) and let the agent loop
      do the rest
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import project_root
from app.llm.client import get_llm
from app.renderers.manim import render_code as _default_render_code
from app.tools.validator import (
    extract_scene_name as _default_extract_scene,
    validate_code as _default_validate,
)

_PROMPT_PATH = project_root / "shared" / "prompts" / "system" / "v1.txt"
_THINK_BLOCK = re.compile(
    r"<\s*\w*think\w*>\s*.*?\s*<\s*/\s*\w*think\w*>",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _strip_md_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_code_from_import(code: str) -> str:
    """Drop everything before the first ``from manim import`` line."""
    lines = code.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("from manim import"):
            return "\n".join(lines[i:]).strip()
    return code.strip()


def _parse_react_response(raw: str) -> dict:
    """Parse LLM output → ``{thought, code}``.

    Tolerates: think blocks, markdown fences, leading/trailing prose.
    """
    text = _THINK_BLOCK.sub("", raw).strip()
    text = _strip_md_fences(text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict) and "code" in parsed:
                return {
                    "thought": str(parsed.get("thought", "")),
                    "code": _extract_code_from_import(str(parsed["code"])),
                }
        except json.JSONDecodeError:
            pass

    return {
        "thought": "(fallback, JSON parse failed)",
        "code": _extract_code_from_import(_strip_md_fences(text)),
    }


async def _call_llm_react(llm, system_prompt: str, user_msg: str) -> dict | None:
    """Single LLM call returning ``{thought, code}`` or None on network error."""
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
    except Exception:
        return None
    raw = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_react_response(raw)


def _build_user_message(prompt: str, prev_error: str | None) -> str:
    """Compose user msg; on retry, the LLM is asked to put a `thought` field."""
    if prev_error is None:
        return prompt
    return (
        f"{prompt}\n\n"
        f"---\n"
        f"上一次运行失败，错误：\n{prev_error}\n\n"
        f"请在 `thought` 字段写出你的反思，在 `code` 字段给出修正后的完整代码。"
    )


# ---------------------------------------------------------------------------
# Public agent class
# ---------------------------------------------------------------------------


@dataclass
class AgentStep:
    """One observable step in the ReAct loop. Used for tests + observability."""
    step: int
    thought: str = ""
    code_len: int = 0
    validation: str = ""
    render: str = ""


@dataclass
class AgentResult:
    code: str | None
    steps: list[AgentStep]


class CoderAgent:
    """Generate + validate + render Manim code with self-correction.

    Usage::

        agent = CoderAgent()
        result = await agent.run("prompt")
        if result.code:
            print("got code", len(result.code))
        else:
            print("failed after", len(result.steps), "steps")

    Dependencies (llm, renderer, validator) can be overridden for testing.
    """

    def __init__(
        self,
        llm=None,
        system_prompt: str | None = None,
        max_steps: int = 6,
        renderer=None,
        validator=None,
        scene_name_extractor=None,
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self.max_steps = max_steps
        self._renderer = renderer  # async (code, scene_name) -> RenderResult
        self._validator = validator  # (code) -> (ok, error)
        self._scene_name_extractor = scene_name_extractor  # (code) -> str | None

    # Lazy defaults so tests can override _llm / _system_prompt before clients init
    @property
    def llm(self):
        return self._llm if self._llm is not None else get_llm()

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt
        return _PROMPT_PATH.read_text(encoding="utf-8")

    async def run(self, prompt: str) -> AgentResult:
        steps: list[AgentStep] = []
        last_error: str | None = None

        for step_idx in range(self.max_steps):
            user_msg = _build_user_message(prompt, last_error)
            llm_result = await _call_llm_react(self.llm, self.system_prompt, user_msg)
            if llm_result is None:
                steps.append(AgentStep(step=step_idx + 1, render="LLM call failed"))
                continue

            thought = llm_result["thought"]
            code = llm_result["code"]
            record = AgentStep(step=step_idx + 1, thought=thought, code_len=len(code))

            # Tool 1: validate (cheap)
            validator = self._validator or _default_validate
            ok, validation_err = validator(code)
            record.validation = "OK" if ok else f"errors: {validation_err}"

            if not ok:
                steps.append(record)
                last_error = f"validate_manim_code 报错：{validation_err}"
                continue

            # Tool 2: render (expensive)
            extractor = self._scene_name_extractor or _default_extract_scene
            scene_name = extractor(code)
            renderer = self._renderer or _default_render_code
            render_result = await renderer(code, scene_name)

            record.render = (
                "rendered ok"
                if (not render_result.error and render_result.video_path)
                else f"render error: {render_result.error or 'no video'}"
            )
            steps.append(record)

            if render_result.error or not render_result.video_path:
                last_error = (
                    f"render_manim_dryrun 报错（manim 真跑失败），\n"
                    f"stderr 末段：\n{render_result.error or 'no video'}\n\n"
                    f"请阅读上面的运行错误，修改代码中真正出 bug 的逻辑（数据下标、"
                    f"边界条件、空对象、API 误用等），重新生成完整代码。"
                )
                continue

            return AgentResult(code=code, steps=steps)

        return AgentResult(code=None, steps=steps)
