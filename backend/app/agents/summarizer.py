"""One-shot LLM call to summarise a (prompt, code) pair into a single sentence.

Used by the few-shots POST endpoint to populate ``few_shots.summary``.
The output is what future RAG retrieval will match against — so it
should:
  * keep the user's original key nouns (so lexical overlap still works)
  * describe what the animation *shows* (so semantic search works)
  * be one short Chinese sentence (so it fits a prompt slot later)

Deliberately NOT wrapped in `create_agent` — there's no tool loop, no
structured output, just a single chat completion.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.client import get_llm


logger = logging.getLogger("thinkcanvas.summarizer")


_SYSTEM = (
    "你是一个简洁的代码标注助手。给定用户的请求和生成的 Manim 动画代码，"
    "请用一句话（≤ 50 字中文）描述这个动画**做了什么**。\n"
    "要求：\n"
    "- 包含用户原始意图里的关键名词\n"
    "- 简明描述动画内容（不要列举代码细节）\n"
    "- 只输出一句话，不要任何解释或前缀"
)


async def summarise_few_shot(prompt: str, code: str) -> str:
    """Return a one-sentence Chinese summary. Never raises — falls back
    to the user's prompt if the LLM misbehaves, so saving still works.
    """
    user_msg = (
        f"用户请求：{prompt}\n\n"
        f"生成的代码（前 60 行）：\n"
        "```python\n"
        + "\n".join(code.splitlines()[:60])
        + "\n```"
    )

    try:
        llm = get_llm()
        result = await llm.ainvoke(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=user_msg)]
        )
        text = (result.content or "").strip()
        # Strip any leading "summary:" / quotes / markdown the model adds.
        text = text.strip("\"'`*").strip()
        if "\n" in text:
            text = text.split("\n", 1)[0].strip()
        if text:
            logger.info(
                "summarise_few_shot.ok prompt_len=%d summary_len=%d",
                len(prompt), len(text),
            )
            return text[:200]
    except Exception:
        logger.exception("summarise_few_shot.failed")

    # Fallback: use the prompt itself. Better than dropping the row.
    return prompt.strip()[:200]


__all__ = ["summarise_few_shot"]
