# 04 · LLM Prompt 设计

> 反映 v1.0 实际状态。Prompt 真相在仓库 [`shared/prompts/system/v1.txt`](../../shared/prompts/system/v1.txt)，本文档是说明。

## 🎯 设计目标

1. **可执行**：LLM 输出必须能直接 `manim file.py Scene` 跑起来
2. **风格统一**：所有动画都是 3Blue1Brown 风格
3. **容错性高**：错误信息能反哺 LLM 自纠
4. **成本可控**：单次生成 < 4K tokens 输出

## 📐 Prompt 三层结构（实际）

```
┌──────────────────────────────────────────────┐
│  Layer 1: System Prompt                      │
│  路径：shared/prompts/system/v1.txt          │
│  内容：硬性约束 + 风格指南 + JSON 输出格式    │
│       + 1 个 few-shot（冒泡排序）            │
├──────────────────────────────────────────────┤
│  Layer 2: Few-shot Examples（动态加载）       │
│  ⚠️ shared/prompts/examples/ 当前是空目录     │
│  v1.0 唯一例子直接嵌在 system prompt 里      │
├──────────────────────────────────────────────┤
│  Layer 3: User Prompt (原始)                 │
│  用户输入 + 上一次错误（重试时）             │
└──────────────────────────────────────────────┘
```

## 📜 System Prompt 真相

**真实位置**：[`shared/prompts/system/v1.txt`](../../shared/prompts/system/v1.txt)

**核心要点**：
- 角色：ThinkCanvas 动画代码生成助手
- 接收中 / 英 prompt
- **强制 JSON 输出**：`{"thought": "...", "code": "..."}`（与原 v0.1 的"纯文本代码"不同）
- `thought` 字段：1-2 句话说明思路或对上一次错误的反思
- `code` 字段：从 `from manim import *` 开始，结尾不加额外内容
- 硬性约束（7 条）：import 限制、类结构、命名、无 LaTeX、无 IO、无循环炸弹、自包含
- 风格指南：黑底 / `BLUE`/`YELLOW`/`GREEN`/`RED` / `rate_func=smooth` / `to_edge` 留白 / 总时长 < 30s

## 🎓 Few-shot 库现状

| 算法 | 状态 | 位置 |
|---|---|---|
| 冒泡排序 | ✅ | 嵌在 system prompt 里 |
| 二分查找 | ❌ 待补 | `shared/prompts/examples/` 当前空 |
| 图 BFS | ❌ 待补 | 同上 |

> v1.0 范围要求 3 个算法 few-shot，目前只剩 1 个。补完前 fallback 到"prompt 描述硬性约束 + 1 个排序例子"。

### 嵌入的冒泡排序示例（v1 当前唯一）

```python
from manim import *


class BubbleSort(Scene):
    def construct(self):
        # 标题
        title = Text("冒泡排序", font_size=48, color=BLUE).to_edge(UP)
        self.play(Write(title))
        self.wait(0.3)

        # 初始数组
        values = [5, 2, 8, 1, 9]
        n = len(values)

        boxes = VGroup(*[
            Square(side_length=0.7, color=BLUE, fill_opacity=0.3)
            for _ in range(n)
        ]).arrange(RIGHT, buff=0.15)

        labels = VGroup(*[Text(str(v), font_size=32) for v in values])
        for box, lbl in zip(boxes, labels):
            lbl.move_to(box.get_center())

        group = VGroup(boxes, labels).shift(DOWN * 0.5)
        self.play(LaggedStart(*[Create(b) for b in boxes], lag_ratio=0.1))
        self.play(LaggedStart(*[Write(l) for l in labels], lag_ratio=0.1))
        self.wait(0.3)

        # 排序过程
        for i in range(n):
            for j in range(n - i - 1):
                self.play(
                    boxes[j].animate.set_fill(YELLOW, opacity=0.6),
                    boxes[j + 1].animate.set_fill(YELLOW, opacity=0.6),
                    run_time=0.25,
                )

                if values[j] > values[j + 1]:
                    values[j], values[j + 1] = values[j + 1], values[j]
                    self.play(
                        Swap(boxes[j], boxes[j + 1]),
                        Swap(labels[j], labels[j + 1]),
                        run_time=0.4,
                    )

                self.play(
                    boxes[j].animate.set_fill(BLUE, opacity=0.3),
                    boxes[j + 1].animate.set_fill(BLUE, opacity=0.3),
                    run_time=0.2,
                )

        self.play(
            LaggedStart(*[b.animate.set_fill(GREEN, opacity=0.6) for b in boxes], lag_ratio=0.1)
        )
        self.wait(1)
```

## 🧪 校验流水线（实际）

实现位置：[`backend/app/tools/validator.py`](../../backend/app/tools/validator.py)

校验顺序：
1. 必须的 import（`from manim import *`）
2. 危险模式黑名单（正则）：
   - `open(`
   - `os.` / `sys.` / `subprocess.` / `shutil.`
   - `requests` / `urllib` / `http.`
   - `eval` / `exec` / `compile`
   - `while True:`
3. AST 解析无 `SyntaxError`
4. 必须存在 `Scene` 子类 + `construct()` 方法

返回 `(ok: bool, error: str)`。

## 🔁 错误重试策略（实际）

### 校验失败重试

实现位置：[`backend/app/agents/react_coder.py`](../../backend/app/agents/react_coder.py) — `create_agent` 内置工具循环

```python
async def validate_only_retry(prompt, llm_call, max_retries=2):
    history = []
    for attempt in range(max_retries + 1):
        # 把历史错误塞进 user message（不是 system）
        user_msg = build_user_message(prompt, history)
        code = await llm_call(user_msg)
        ok, error = validate_code(code)
        if ok:
            return code, attempt
        history.append({"prev_error": error})
    return None, attempt
```

### 渲染失败重试

**当前未实现自动修复**：渲染失败时把 stderr 回喂 LLM 修代码——这一步 **v1.0 没接**，只校验错误会重试。  
TODO：v1.x 在 `coder.py` 里加 `render_retry_with_fix`。

## 🎯 Few-shot 选择策略（规划）

### 简单方案（v1.0 暂未做）
**关键词匹配**：
- 包含"排序" → 给冒泡排序例子
- 包含"搜索/查找" → 给二分查找例子
- ...

### 进阶方案（v1.x）
**Embedding 检索** + 维持 10-20 个高质量动画。

## 📊 评估方法（Step 6 待做）

```python
SEED_PROMPTS = [
    ("冒泡排序", "bubble_sort"),
    ("二分查找", "binary_search"),
    ("图的广度优先搜索", "graph_bfs"),
]
# 3 个算法 × 10 次，记录成功率 / 时长
```

## 🧰 调试工具

- **看 LLM 实际输出**：当前没有专门的 debug endpoint；下一步可加 `GET /api/v1/debug/last-prompt`
- **Manim 沙箱日志**：写在 `renderers/manim.py` 的 logger（`logger.info(code)` / `logger.info(result.stderr)`）

## 📚 Few-shot 库建设

每个种子算法需要：
1. ✅ 能跑的 Manim 代码
2. ✅ 对应的 prompt 模板
3. ✅ 预期输出
4. ✅ 评测标准

**当前状态**：仅 1/3 完成。

## 🚀 迭代计划

| 版本 | Few-shot 数 | Prompt 策略 |
|---|---|---|
| **v1.0 当前** | 1（冒泡） | 关键词 / 全部塞 system |
| **v1.0 TODO** | 3（冒泡 + 二分 + BFS） | 同上 |
| **v1.x** | 5-10 | 按 prompt 动态选 1-2 个 |
| **v2.x** | 20+ | Embedding 检索 |

## ❓ 待验证

- [ ] MiniMax-M3 对 Manim API 的记忆准确度
- [ ] Few-shot 数量对成功率的影响曲线
- [ ] 中文 vs 英文 prompt 的差异
- [ ] 错误信息给 LLM 后修复成功率
- [ ] 输出长度限制的最佳实践
- [ ] JSON 输出 vs 纯文本输出的稳定性对比
