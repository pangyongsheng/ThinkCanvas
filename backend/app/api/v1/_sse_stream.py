"""SSE 通用工具：把回调吐的事件序列化成 ``text/event-stream``。

约定：

* ``OnEvent = Callable[[str, dict], Awaitable[None]]`` — runner 收到这个回调，
  把事件 push 到队列
* ``stream_from_runner(runner, initial_events=...)`` — outer async generator，
  先 yield ``initial_events``，再从队列取事件直到收到 ``done`` 或 ``failed``
* runner 抛错由 outer 包成 ``{"error": ...}`` ``failed`` 事件再退出
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable


logger = logging.getLogger("thinkcanvas.api.sse_stream")

OnEvent = Callable[[str, dict], Awaitable[None]]


def _sse(event: str, data: dict) -> str:
    """单条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_from_runner(
    runner: Callable[[OnEvent], Awaitable[None]],
    *,
    initial_events: list[tuple[str, dict]] | None = None,
    final_done_payload: dict | None = None,
) -> AsyncIterator[str]:
    """包装 runner 为 SSE async generator。

    流程：
      1. 先 yield ``initial_events``（如果有）
      2. 启动 runner 任务，runner 通过 on_event 把事件 push 进队列
      3. 从队列读事件 → yield SSE 帧
      4. 收到 ``done`` / ``failed`` 终止循环
      5. runner 抛错时记 log 并 yield ``failed`` 事件再退出
    """
    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    async def on_event(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def _runner_wrapper() -> None:
        try:
            await runner(on_event)
        except Exception:
            logger.exception("stream_from_runner.runner crashed")
            await queue.put(("failed", {"error": "internal server error"}))

    task = asyncio.create_task(_runner_wrapper())

    try:
        for event, data in (initial_events or []):
            yield _sse(event, data)

        while True:
            event, data = await queue.get()
            yield _sse(event, data)
            if event in ("done", "failed"):
                break
    finally:
        await task


__all__ = ["OnEvent", "_sse", "stream_from_runner"]
