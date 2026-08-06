"""ReAct-style agent entry point — ``create_agent`` standard.

Wraps the agent factory with a thin async helper that:

  * builds the agent (style-aware)
  * invokes it with the user's prompt
  * extracts the structured ``CodeOutput`` from the final state
  * returns a compact dict the HTTP layer can serialise
  * captures any exception with full traceback for debuggability
  * gracefully recovers when the LLM leaks its ``thinking`` channel into
    the text portion of the reply (notably MiniMax-M3)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.builder import build_agent
from app.agents.state import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID
from app.core.logging import log_exception


logger = logging.getLogger("thinkcanvas.agent")


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def run_agent(
    prompt: str,
    *,
    style_id: str = DEFAULT_STYLE_ID,
    max_iterations: int = 6,
) -> dict:
    """Build + invoke the standard LangChain agent.

    Returns
    -------
    dict
        ``{"code": str|None, "tool_log": [...], "messages": [...]}``
    """
    agent = build_agent(style_id=style_id)
    return await _invoke_and_extract(
        agent,
        {"messages": [HumanMessage(content=prompt)]},
        max_iterations=max_iterations,
        label="agent.run",
        style_id=style_id,
    )


# ---------------------------------------------------------------------------
# Shared invoke + extraction pipeline
# ---------------------------------------------------------------------------

async def _invoke_and_extract(
    agent,
    invoke_input: dict,
    *,
    max_iterations: int,
    label: str,
    style_id: str,
) -> dict:
    """Run ``agent.ainvoke`` and extract the structured code.

    Recovery order (per attempt):
      1. Plain ``response_format=CodeOutput`` response — best case.
      2. Code hidden inside a typed-block list (MiniMax ``[thinking, text]``).
      3. Aggressive scan: every string-valued field of every block.
      4. First ```` ```python ... ``` ```` fence in any string field.

    Whole-pipeline retry:
      If every fallback fails AND the final ``text`` block is effectively
      empty (< 50 chars), retry once. This recovers from the case where
      the LLM burned its budget inside the thinking channel and never
      produced a real answer.
    """
    config = cast(
        RunnableConfig,
        {"recursion_limit": max_iterations * 4 + 1},
    )

    last_result = None
    for attempt in range(2):  # original + 1 retry
        try:
            result = await agent.ainvoke(invoke_input, config=config)
        except Exception:
            if attempt == 0:
                logger.warning(
                    "%s.ainvoke_error style=%s — retrying once",
                    label, style_id,
                )
                continue
            log_exception(logger, f"{label} ainvoke failed (after retry)")
            raise
        last_result = result
        if not _looks_truncated(result):
            break
        if attempt == 0:
            logger.warning(
                "%s.truncated_retry style=%s — output looks truncated; "
                "retrying once",
                label, style_id,
            )

    if last_result is None:
        raise RuntimeError(f"{label}: ainvoke returned no result")
    return _extract_from_result(last_result, label=label, style_id=style_id)


def _looks_truncated(result: dict) -> bool:
    """True when the LLM spent budget inside ``thinking`` but the
    ``text`` portion is essentially empty (whitespace only or < 20 chars)
    AND the JSON answer never made it out.

    Only ``list`` content (MiniMax typed blocks) qualifies — a plain
    string reply that the model chose to keep short does NOT count as
    truncated; the LLM might have legitimately said "no".
    """
    messages = result.get("messages", [])
    if not messages:
        return False
    if result.get("structured_response") is not None:
        return False
    last = messages[-1]
    content = getattr(last, "content", "")
    if not isinstance(content, list):
        return False
    has_thinking = False
    text_payload = ""
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "thinking":
            has_thinking = True
        if b.get("type") in {"text", "output_text"}:
            text_payload += (b.get("text") or "")
    if not has_thinking:
        return False
    return len(text_payload.strip()) < 20


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _extract_from_result(
    result: dict, *, label: str, style_id: str
) -> dict:
    """Apply the tiered fallback chain and shape the final response dict."""
    structured = result.get("structured_response")
    messages = result.get("messages", [])

    tool_log: list[dict] = []
    final_code: str | None = None

    if structured is not None:
        final_code = structured.code

    if not final_code:
        recovered = _recover_code_from_messages(messages)
        if recovered:
            final_code = recovered
            logger.info(
                "%s.fallback_recovered style=%s code_len=%d",
                label, style_id, len(final_code),
            )
        else:
            aggressive = _aggressive_scan_for_code(messages)
            if aggressive:
                final_code = aggressive
                logger.info(
                    "%s.aggressive_recovered style=%s code_len=%d",
                    label, style_id, len(final_code),
                )
            else:
                fence = _extract_python_fence_from_messages(messages)
                if fence:
                    final_code = fence
                    logger.info(
                        "%s.fence_recovered style=%s code_len=%d",
                        label, style_id, len(final_code),
                    )

    if not final_code:
        try:
            logger.warning(
                "%s.no_code_dump style=%s messages=%d msgs=%s structured=%s",
                label, style_id, len(messages),
                [(type(m).__name__, _content_dump(m)) for m in messages],
                repr(structured)[:600] if structured is not None else "None",
            )
        except Exception:  # noqa: BLE001
            pass

    for msg in messages:
        for tc in (getattr(msg, "tool_calls", None) or []):
            tool_log.append({
                "tool": tc.get("name"),
                "args": {k: str(v)[:200] for k, v in (tc.get("args") or {}).items()},
                "id": tc.get("id"),
            })

    logger.info(
        "%s.end code=%s tool_calls=%d messages=%d",
        label, "OK" if final_code else "NONE",
        len(tool_log), len(messages),
    )

    return {
        "code": final_code,
        "tool_log": tool_log,
        "messages": [str(getattr(m, "content", m)) for m in messages],
    }


def _content_preview(message: Any, limit: int = 200) -> Any:
    """Short, truncated preview used for ordinary logs."""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return [
            (b.get("type") if isinstance(b, dict) else type(b).__name__, str(b)[:limit])
            for b in content
        ]
    return content


def _content_dump(message: Any) -> Any:
    """Full-fidelity dump, used only in the warning path when no code
    was recovered — so we can see exactly what the LLM sent without
    the 200-char truncation.
    """
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return [
            (b.get("type") if isinstance(b, dict) else type(b).__name__, repr(b))
            for b in content
        ]
    return repr(content)


def _flatten_blocks(blocks: list) -> str:
    """Concatenate only the text-bearing blocks from a list content.

    Drops ``thinking`` (kept for diagnostics only), ``reasoning`` and any
    other non-text blocks. Joins ``text`` blocks with newlines.
    """
    keep_types = {"text", "output_text", "code"}
    out: list[str] = []
    for b in blocks:
        if isinstance(b, str):
            out.append(b)
            continue
        if not isinstance(b, dict):
            continue
        if b.get("type") in keep_types:
            text = b.get("text") or b.get("content") or ""
            if isinstance(text, str) and text.strip():
                out.append(text)
    return "\n".join(out)


def _parse_code_object(payload: str) -> str | None:
    """Try to extract a runnable ``code`` string from a JSON-looking payload."""
    try:
        obj = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    code_val = obj.get("code")
    if not isinstance(code_val, str):
        return None
    try:
        return CodeOutput(thought=str(obj.get("thought", "")), code=code_val).code
    except Exception:  # noqa: BLE001
        return None


def _recover_code_from_messages(messages: list) -> str | None:
    """First-pass recovery: scan messages for ``text`` blocks or fenced JSON."""
    candidates: list[str] = []
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            flat = _flatten_blocks(content)
            if flat.strip():
                candidates.append(flat)
            continue
        if isinstance(content, str):
            text = content.strip()
            if not text:
                continue
            fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
            if fence_match:
                candidates.append(fence_match.group(1))
            else:
                candidates.append(text)

    for cand in candidates:
        if (code := _parse_code_object(cand)):
            return code
        for m in _JSON_OBJECT_RE.finditer(cand):
            if (code := _parse_code_object(m.group(0))):
                return code
    return None


def _aggressive_scan_for_code(messages: list) -> str | None:
    """Last-resort: scan every block, every string field for JSON-shaped content.

    Some providers (MiniMax under load, observed in production) wrap their
    final answer in unexpected block types like ``tool_use.input`` or even
    nest the JSON inside a ``thinking`` block's prose. Whitelist-based
    scanning misses those; this recursively descends and tries
    ``json.loads`` on every plausible string.
    """
    def _walk_strings(obj: Any, found: list[str]) -> None:
        if isinstance(obj, str):
            if "{" in obj and "}" in obj and len(obj) > 50:
                found.append(obj)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                _walk_strings(v, found)
            return
        if isinstance(obj, list):
            for v in obj:
                _walk_strings(v, found)

    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if not isinstance(content, list):
            if isinstance(content, str) and "{" in content:
                if (code := _parse_code_object(content)):
                    return code
            continue
        candidates: list[str] = []
        _walk_strings(content, candidates)
        candidates.sort(key=len, reverse=True)
        for cand in candidates:
            if (code := _parse_code_object(cand)):
                return code
            for m in _JSON_OBJECT_RE.finditer(cand):
                if (code := _parse_code_object(m.group(0))):
                    return code
    return None


__all__ = ["run_agent", "_invoke_and_extract"]
def _extract_python_fence(text: str) -> str | None:
    """Pull the first ```python ... ``` block out of arbitrary text.

    MiniMax under load often emits the full answer inside a ``thinking``
    block as a markdown code fence instead of returning structured JSON.
    This picks the longest ``python ... `` fenced block
    block as the most-likely-intended code body.
    """
    matches = re.findall(r"```(?:python|py)?\s*\n([\s\S]+?)\n```", text)
    if not matches:
        return None
    # Longest block is usually the actual implementation (others are
    # examples the model was thinking through).
    return max(matches, key=len).strip()
def _extract_python_fence_from_messages(messages: list) -> str | None:
    """Walk all blocks; if any string contains a markdown python fence
    that looks like a full Manim Scene, return its body.

    Filters out tiny snippets (e.g. one-line ``print`` examples); only
    fences whose body starts with ``from manim`` and defines a ``Scene``
    subclass count as candidates.
    """
    candidates: list[str] = []
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        strings: list[str] = []
        if isinstance(content, str):
            strings.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, str):
                    strings.append(b)
                elif isinstance(b, dict):
                    for v in b.values():
                        if isinstance(v, str):
                            strings.append(v)
        for s in strings:
            fence = _extract_python_fence(s)
            if not fence:
                continue
            head = fence[:200]
            if "from manim import" in head and "Scene" in head:
                candidates.append(fence)
    if not candidates:
        return None
    # Longest plausible answer.
    return max(candidates, key=len)
