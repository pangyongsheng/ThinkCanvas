"""``create_agent`` + ``response_format`` 不够用时的多层兜底。

MiniMax-M3 经常把答案塞在 ``thinking`` 块里输出，于是这些 helper 就负责把它挖出来：

  1. ``invoke_with_recovery``             — 外层驱动；输出疑似截断时 1-shot 重试
  2. ``extract_from_result``              — 根据 result 选对应的兜底层
  3. ``_recover_code_from_messages``      — text 块扫描 + JSON 对象匹配
  4. ``_aggressive_scan_for_code``        — 对每个字符串字段递归 ``json.loads``
  5. ``_extract_python_fence_from_messages`` — 抽出最长的 ```python 代码栅栏
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.schemas import CodeOutput
from app.core.logging import log_exception


logger = logging.getLogger("thinkcanvas.agent.recovery")


# Regex matching the outermost JSON object. Crude on purpose: we only fall
# back to this when ``with_structured_output`` failed, so the goal is to
# catch common "LLM emitted CodeOutput-shaped JSON inline" cases.
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


# ---------------------------------------------------------------------------
# Outer driver: tiered recovery + 1-shot retry
# ---------------------------------------------------------------------------

async def invoke_with_recovery(
    agent,
    invoke_input: dict,
    *,
    max_iterations: int,
    label: str,
    style_id: str,
    callbacks: list | None = None,
) -> dict:
    """调用 ``agent.ainvoke`` 并通过多层兜底链恢复代码。

    单次尝试里的恢复顺序：
      1. 标准 ``response_format=CodeOutput`` 响应 — 最佳情况
      2. 代码藏在 typed-block 列表里（MiniMax 的 ``[thinking, text]``）
      3. 暴力扫描：每个 block 的每个字符串字段都试一次
      4. 任意字符串字段里第一个 ```python 代码栅栏

    整轮重试：
      如果所有兜底都失败、且最终的 ``text`` 块几乎是空的
      （< 20 字符），就重试一次。这能救回一种情况：LLM 把预算
      全烧在 thinking 里，根本没产出真正的答案。
    """
    config = {"recursion_limit": max_iterations * 4 + 1}  # type: ignore[dict-item]
    if callbacks:
        config["callbacks"] = callbacks  # type: ignore[dict-item]

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
    return extract_from_result(last_result, label=label, style_id=style_id)


# ---------------------------------------------------------------------------
# Per-result extraction
# ---------------------------------------------------------------------------

def _looks_truncated(result: dict) -> bool:
    """判断 LLM 输出是否疑似截断。

    当 LLM 把预算都花在 ``thinking`` 里、最终 ``text`` 块几乎是空的
    （空白或 < 20 字符），且 JSON 答案也没出来时返回 True。

    只有 ``list`` 类型的内容（MiniMax 的 typed blocks）才算截断 —
    普通字符串回复被刻意写得很短不算截断，因为 LLM 可能本来就想说"不"。
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


def _truncate_dict(d: dict, *, limit: int) -> dict:
    """把 dict 里的所有字符串值截到 ``limit`` 字符，非字符串原样保留。"""
    return {
        k: (v[:limit] if isinstance(v, str) else v)
        for k, v in d.items()
    }


def extract_from_result(result: dict, *, label: str, style_id: str) -> dict:
    """按多层兜底链执行提取，并组装成最终的响应 dict。"""
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

    # 同时收集 tool_log（旧汇总）和 tool_steps（新明细）。
    # tool_steps 包含 tool_call 和对应 tool_result，按 step_index 顺序排列，
    # 落 agent_steps 表用。tool_call_id 配对 AIMessage.tool_calls 和 ToolMessage。
    tool_steps: list[dict] = []
    pending_calls: dict[str, dict] = {}  # tool_call_id -> 最近的 tool_call step

    for idx, msg in enumerate(messages):
        msg_type = type(msg).__name__

        # AIMessage 带 tool_calls → 记录调用
        for tc in (getattr(msg, "tool_calls", None) or []):
            tc_id = tc.get("id")
            step = {
                "step_index": idx,
                "step_type": "tool_call",
                "tool_name": tc.get("name"),
                "tool_call_id": tc_id,
                "tool_args": _truncate_dict(tc.get("args") or {}, limit=1000),
                "tool_result": None,
                "error": None,
            }
            tool_steps.append(step)
            if tc_id:
                pending_calls[tc_id] = step
            tool_log.append({
                "tool": step["tool_name"],
                "args": {k: str(v)[:200] for k, v in (tc.get("args") or {}).items()},
                "id": tc_id,
            })

        # ToolMessage → 把 result/error 写回对应 tool_call step
        if msg_type == "ToolMessage":
            tc_id = getattr(msg, "tool_call_id", None)
            content = getattr(msg, "content", "")
            status = getattr(msg, "status", "ok")
            result_text = str(content)[:4000]
            if tc_id and tc_id in pending_calls:
                pending_calls[tc_id]["tool_result"] = result_text
                if status != "ok":
                    pending_calls[tc_id]["error"] = result_text
            else:
                # 孤儿 ToolMessage（没匹配到 AIMessage.tool_call），单独落一条
                tool_steps.append({
                    "step_index": idx,
                    "step_type": "tool_result",
                    "tool_name": getattr(msg, "name", None),
                    "tool_call_id": tc_id,
                    "tool_args": None,
                    "tool_result": result_text,
                    "error": None if status == "ok" else result_text,
                })

    logger.info(
        "%s.end code=%s tool_calls=%d steps=%d messages=%d",
        label, "OK" if final_code else "NONE",
        len(tool_log), len(tool_steps), len(messages),
    )

    return {
        "code": final_code,
        "tool_log": tool_log,
        "tool_steps": tool_steps,
        "messages": [str(getattr(m, "content", m)) for m in messages],
    }


# ---------------------------------------------------------------------------
# Tiers 2-4: recovery helpers
# ---------------------------------------------------------------------------

def _content_dump(message: Any) -> Any:
    """把 message 原样 dump 出来，只在警告路径（没救回代码时）使用，
    这样我们能看清 LLM 究竟发了什么。
    """
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return [
            (b.get("type") if isinstance(b, dict) else type(b).__name__, repr(b))
            for b in content
        ]
    return repr(content)


def _flatten_blocks(blocks: list) -> str:
    """只把 list 类型的 content 里带文本的 block 拼起来。

    丢弃 ``thinking``（只留作诊断用）、``reasoning`` 以及其他非文本 block；
    多个 ``text`` block 之间用换行连接。
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
    final answer in unexpected block types. Whitelist-based scanning misses
    those; this recursively descends and tries ``json.loads`` on every
    plausible string.
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


def _extract_python_fence(text: str) -> str | None:
    """Pull the first fenced code block out of arbitrary text.

    MiniMax under load often emits the full answer inside a ``thinking``
    block as a markdown code fence instead of returning structured JSON.
    Returns the longest fence body if multiple are present.
    """
    matches = re.findall(r"```(?:python|py)?\s*\n([\s\S]+?)\n```", text)
    if not matches:
        return None
    return max(matches, key=len).strip()


def _extract_python_fence_from_messages(messages: list) -> str | None:
    """Look for ``from manim import``-anchored fences in any string field."""
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
    return max(candidates, key=len)


__all__ = [
    "invoke_with_recovery",
    "extract_from_result",
    "_looks_truncated",
    "_flatten_blocks",
    "_parse_code_object",
    "_recover_code_from_messages",
    "_aggressive_scan_for_code",
    "_extract_python_fence_from_messages",
    "_content_dump",
]
