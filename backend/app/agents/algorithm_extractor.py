"""从 (user prompt, generated code) 中抽出规范化算法名。

用途：
  * ``AgentService.run_initial / run_refine`` 在主流程跑完后，**异步**
    调一次本模块抽 algorithm_name + status，upsert 到
    ``user_algorithm_history`` 表。
  * 不阻塞主流程 —— 失败只丢一条记忆，不影响生成结果。
  * embedding 同步生成一次 —— 后续去重时算相似度用。

抽名 prompt 要求：
  * 输出**英文短名词**（"bubble sort" / "binary search"）—— 跨语言去重
  * 找不到明确算法时输出 "general"（不要瞎猜）
  * 单一字段直接 JSON 输出，调用方 parse 失败就 fallback 到 "general"
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.summarizer import _extract_text_from_message
from app.llm.client import get_llm
from app.services.embeddings import embed_one


logger = logging.getLogger("thinkcanvas.agents.algorithm_extractor")


_SYSTEM = (
    "你是一个算法分类助手。给定用户的请求和生成的 Manim 动画代码，"
    "请输出这个动画展示的算法名称。\n"
    "要求：\n"
    "- 输出**英文短名词**（例如 'bubble sort' / 'binary search' / 'merge sort' / "
    "'graph BFS' / 'matrix multiplication'）\n"
    "- 长度 ≤ 30 字符\n"
    "- 找不到明确算法时输出 'general'\n"
    "- 只输出一个 JSON 对象：{\"algorithm\": \"<name>\"}，不要其他文字"
)


def _parse_algorithm(payload: str) -> str:
    """从 LLM 输出里解析出 algorithm 字段，失败回落到 'general'。"""
    if not payload:
        return "general"
    payload = payload.strip()
    # 兼容 ```json ... ``` 包裹
    if payload.startswith("```"):
        payload = payload.strip("`").strip()
        if payload.startswith("json"):
            payload = payload[4:].strip()
    try:
        obj = json.loads(payload)
        algo = obj.get("algorithm")
        if isinstance(algo, str) and algo.strip():
            return algo.strip()[:100].lower()
    except (ValueError, AttributeError):
        pass
    return "general"


async def extract_algorithm_name(
    *,
    user_prompt: str,
    code: str,
) -> tuple[str, list[float] | None]:
    """抽 (algorithm_name, embedding)。

    返回 (name, embedding_or_None)。任一失败都返回 ("general", None)，
    不抛异常 —— 这是后台 fire-and-forget 任务，不能阻塞主流程。
    """
    user_msg = (
        f"用户请求：{user_prompt}\n\n"
        f"生成的代码（前 60 行）：\n"
        "```python\n"
        + "\n".join((code or "").splitlines()[:60])
        + "\n```"
    )

    algo_name = "general"
    try:
        llm = get_llm()
        result = await llm.ainvoke(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=user_msg)]
        )
        text = _extract_text_from_message(getattr(result, "content", None))
        algo_name = _parse_algorithm(text)
        logger.info(
            "algorithm_extractor.llm_ok algo=%s prompt_len=%d",
            algo_name, len(user_prompt),
        )
    except Exception:
        logger.exception("algorithm_extractor.llm_failed prompt_len=%d", len(user_prompt))

    # Embedding 单独算 —— LLM 调通但 embedding 加载失败也不影响 algo 本身
    embedding: list[float] | None = None
    try:
        embedding = embed_one(algo_name, is_query=False)
    except Exception:
        logger.warning(
            "algorithm_extractor.embed_failed algo=%s — name-only stored",
            algo_name,
        )

    return algo_name, embedding


__all__ = ["extract_algorithm_name"]
