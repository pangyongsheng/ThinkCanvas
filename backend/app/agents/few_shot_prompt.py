"""把 FewShot 列表格式化成 system prompt 片段。

每条示例输出成：
    ### 例 N · <style>
    **题目**: <prompt>
    **代码**:
    ```python
    <code>
    ```

空列表返回空字符串 — 调用方自己判断要不要写"以下是范例"标题。
"""
from __future__ import annotations

from app.db.models import FewShot


def format_few_shot_block(few_shots: list[FewShot]) -> str:
    """FewShot 列表 → markdown 片段。

    顺序就是 FewShot 列表的顺序（retriever 已经按相似度排好）。
    """
    if not few_shots:
        return ""
    chunks: list[str] = []
    for i, fs in enumerate(few_shots, start=1):
        chunks.append(
            f"### 例 {i} · {fs.style}\n"
            f"**题目**: {fs.prompt.strip()}\n"
            f"**代码**:\n"
            f"```python\n{fs.code.rstrip()}\n```"
        )
    return "\n\n".join(chunks)


def with_few_shot_header(few_shots: list[FewShot]) -> str:
    """带"以下是用户收藏的范例"标题的完整片段。"""
    body = format_few_shot_block(few_shots)
    if not body:
        return ""
    return (
        "## 以下是用户收藏的范例（按相似度排序）\n"
        "请参考这些例子的风格、结构与完成度，但不要照搬。\n\n"
        + body
    )


__all__ = ["format_few_shot_block", "with_few_shot_header"]
