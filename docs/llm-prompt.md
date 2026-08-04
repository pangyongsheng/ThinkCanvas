# 04 · LLM Prompt 设计

> 这是 ThinkCanvas 的**灵魂**。LLM 写出能跑的 Manim 代码，整个产品才能成立。

## 🎯 设计目标

1. **可执行**：LLM 输出必须能直接 `manim file.py Scene` 跑起来
2. **风格统一**：所有动画都是 3Blue1Brown 风格
3. **容错性高**：错误信息能反哺 LLM 自纠
4. **成本可控**：单次生成 < 4K tokens 输出

## 📐 Prompt 三层结构

```
┌──────────────────────────────────────────────┐
│  Layer 1: System Prompt (固定)               │
│  - 角色定义                                  │
│  - 硬性约束（导入、类结构、安全）             │
│  - 风格指南（颜色、字号、缓动）               │
│  - 输出格式（无 markdown）                    │
├──────────────────────────────────────────────┤
│  Layer 2: Few-shot Examples (动态选)         │
│  - 根据用户 prompt 选最相似的 1-2 个        │
│  - 提供完整可运行代码                        │
├──────────────────────────────────────────────┤
│  Layer 3: User Prompt (原始)                 │
│  - 用户输入的文字描述                        │
└──────────────────────────────────────────────┘
```

## 📜 System Prompt (v1)

```markdown
你是 ThinkCanvas 的动画代码生成助手。根据用户描述，生成可直接运行的
ManimCE Python 代码。

# 硬性约束（违反则视为失败）
1. **导入**：只允许 `from manim import *`，禁止其他导入
2. **类结构**：必须定义 `class SceneName(Scene)`，方法名 `construct`
3. **命名**：类名用 PascalCase，且能从 prompt 推断出含义
4. **无 LaTeX**：用 `Text()` 代替 `MathTex()` / `Tex()`
5. **无 IO**：禁止文件读写、网络请求、`os` / `subprocess` / `open`
6. **无循环炸弹**：避免 `while True`、超长循环（动画帧数 < 600）
7. **自包含**：不依赖任何外部资源（图片、字体、文件）

# 风格指南
- 背景：默认黑/深灰（`background_color = "#1e1e1e"` 不需要写，Manim 默认是黑）
- 主色：`BLUE`、`YELLOW`、`GREEN`、`RED`（Manim 内置常量）
- 字号：标题 48-72，正文 24-36，注释 18
- 缓动：`rate_func=smooth` 或 `rate_func=ease_in_out`
- 动画时长：单步 0.3-1.0s，总时长 < 30s
- 排版：用 `to_edge(UP/DOWN/LEFT/RIGHT)` 留出边距

# 输出格式
- 纯 Python 代码，**不**用 markdown 代码块包裹
- 第一个非空行必须是 `from manim import *`
- 不要任何解释、注释（除了代码内的中文注释）
- 末尾不加任何额外内容
```

## 🎓 Few-shot 例子

> 完整代码存放在 `shared/prompts/examples/`

### 1. 冒泡排序
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
                # 高亮比较
                self.play(
                    boxes[j].animate.set_fill(YELLOW, opacity=0.6),
                    boxes[j + 1].animate.set_fill(YELLOW, opacity=0.6),
                    run_time=0.25,
                )

                if values[j] > values[j + 1]:
                    # 交换数据
                    values[j], values[j + 1] = values[j + 1], values[j]
                    self.play(
                        Swap(boxes[j], boxes[j + 1]),
                        Swap(labels[j], labels[j + 1]),
                        run_time=0.4,
                    )

                # 恢复颜色
                self.play(
                    boxes[j].animate.set_fill(BLUE, opacity=0.3),
                    boxes[j + 1].animate.set_fill(BLUE, opacity=0.3),
                    run_time=0.2,
                )

        # 全部高亮完成
        self.play(
            LaggedStart(*[b.animate.set_fill(GREEN, opacity=0.6) for b in boxes], lag_ratio=0.1)
        )
        self.wait(1)
```

## 🧪 校验流水线

```python
import ast
import re

REQUIRED_IMPORT = "from manim import *"
DANGEROUS_PATTERNS = [
    r"\bopen\s*\(",                    # 文件操作
    r"\b(os\.|sys\.|subprocess\.|shutil\.)",  # 系统调用
    r"\b(requests|urllib|http)\.",      # 网络
    r"\b(eval|exec|compile)\s*\(",      # 动态执行
    r"while\s+True\s*:",                # 死循环
]


def validate_code(code: str) -> tuple[bool, str]:
    """校验 LLM 输出的代码"""
    # 1. 必须的 import
    if REQUIRED_IMPORT not in code:
        return False, "missing required import: from manim import *"

    # 2. 危险模式
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            return False, f"dangerous pattern detected: {pattern}"

    # 3. AST 解析
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    # 4. 必须有 Scene 子类
    has_scene = any(
        isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Name) and base.id == "Scene"
            for base in node.bases
        )
        and any(
            isinstance(child, ast.FunctionDef) and child.name == "construct"
            for child in node.body
        )
        for node in ast.walk(tree)
    )
    if not has_scene:
        return False, "no Scene subclass with construct() found"

    return True, ""
```

## 🔁 错误重试策略

### 校验失败重试

```python
async def generate_with_retry(
    prompt: str,
    llm_client,
    max_retries: int = 2,
) -> str:
    history = []  # [(code, error), ...]

    for attempt in range(max_retries + 1):
        # 构造 prompt，把历史错误加进去
        system_prompt = build_system_prompt(history)

        # 调用 LLM
        code = await llm_client.generate(
            system=system_prompt,
            user=prompt,
            few_shot=select_few_shot(prompt),
        )

        # 校验
        ok, error = validate_code(code)
        if ok:
            return code

        # 记录错误
        history.append((code, error))
        logger.warning(f"Attempt {attempt + 1} failed: {error}")

    raise ValidationError(f"Failed after {max_retries + 1} attempts")
```

### 渲染失败重试

```python
async def render_with_retry(code: str, llm_client, max_retries: int = 1):
    history = []

    for attempt in range(max_retries + 1):
        try:
            video_path = await run_manim(code, timeout=60)
            return video_path
        except ManimError as e:
            history.append((code, e.stderr))
            if attempt < max_retries:
                # 把错误信息给 LLM，让它修
                code = await llm_client.fix(code, e.stderr)
            else:
                raise
```

## 🎯 Few-shot 选择策略

### 简单方案（v0.1）
**关键词匹配**：
- 包含"排序" → 给冒泡排序例子
- 包含"搜索/查找" → 给二分查找例子
- 包含"树" → 给 BFS/DFS 例子
- ...

### 进阶方案（v0.5）
**Embedding 检索**：
- 维护 10-20 个高质量动画
- 用户 prompt → embedding → 找最相似的 1-2 个
- 塞进 prompt

## 📊 评估方法

### 自动化（CI 里跑）
```python
SEED_PROMPTS = [
    ("冒泡排序", "bubble_sort"),
    ("快速排序", "quick_sort"),
    ("归并排序", "merge_sort"),
    ("二分查找", "binary_search"),
    ("栈的入栈出栈", "stack"),
    ("队列", "queue"),
    ("链表反转", "linked_list"),
    ("二叉树层序遍历", "bst_bfs"),
    ("二叉树深度优先遍历", "bst_dfs"),
    ("图的广度优先搜索", "graph_bfs"),
]


async def benchmark():
    results = []
    for prompt, _ in SEED_PROMPTS:
        try:
            code = await generate_with_retry(prompt, client)
            video = await render_with_retry(code, client)
            results.append({"prompt": prompt, "ok": True, "time": ...})
        except Exception as e:
            results.append({"prompt": prompt, "ok": False, "error": str(e)})

    success_rate = sum(1 for r in results if r["ok"]) / len(results)
    print(f"Success rate: {success_rate:.0%}")
```

### 人工评估（5 分制）
- **正确性**：算法逻辑对不对
- **可读性**：看动画能不能理解算法
- **美观度**：视觉效果好不好
- **流畅度**：动画过渡自不自然

## 🧰 调试工具

### 看 LLM 实际输出
```python
# backend 接口
@app.get("/api/debug/last-prompt")
async def last_prompt():
    return {
        "system": last_system_prompt,
        "user": last_user_prompt,
        "examples": last_few_shot,
        "output": last_llm_output,
    }
```

### Manim 沙箱日志
```python
# 渲染时记录
logger.info(f"Code:\n{code}")
logger.info(f"stdout: {result.stdout}")
logger.info(f"stderr: {result.stderr}")
logger.info(f"returncode: {result.returncode}")
```

## 📚 Few-shot 库建设

每个种子算法需要：
1. ✅ 能跑的 Manim 代码
2. ✅ 对应的 prompt（用户怎么描述它）
3. ✅ 预期输出（生成的视频大致什么样）
4. ✅ 评测标准（怎么算"好"）

**进度追踪**：`shared/prompts/INDEX.md`

```markdown
# Few-shot 库索引

| 算法 | prompt 模板 | 代码 | 状态 |
|---|---|---|---|
| 冒泡排序 | "冒泡排序"、"bubble sort" | [bubble_sort.py](examples/bubble_sort.py) | ✅ |
| 快速排序 | "快速排序"、"quicksort" | [quick_sort.py](examples/quick_sort.py) | 🚧 |
```

## 🚀 迭代计划

- **v1**：固定 System Prompt + 2-3 个 few-shot（足够启动）
- **v2**：根据 prompt 动态选 few-shot
- **v3**：Embedding 检索 + 100+ 高质量例子
- **v4**：用户反馈学习（用户点赞/差评 → 微调）

## ❓ 待验证

- [ ] DeepSeek-V3 对 Manim API 的记忆准确度
- [ ] Few-shot 数量对成功率的影响曲线
- [ ] 中文 vs 英文 prompt 的差异
- [ ] 错误信息给 LLM 后修复成功率
- [ ] 输出长度限制的最佳实践
