# 04 · LLM Prompt 设计

> 反映 v1.0 **当前**实际状态（2026-08 P3 更新）。
>
> 关键演进：v1.0 早期是"1 个硬编码 few-shot 嵌 system prompt"；当前改为 **few_shots 表 + embedding 召回**（retriever），加了**长期记忆块**和 **Script Designer 提示词**。

## 🎯 设计目标

1. **可执行**：LLM 输出必须能直接 `manim file.py Scene` 跑起来
2. **风格统一**：所有动画 3Blue1Brown / academic / minimal 三选一
3. **容错性高**：错误信息能反哺 LLM 自纠（Reviewer 节点 + 4 层兜底）
4. **成本可控**：单次生成 < 4K tokens 输出
5. **个性化**：跨会话学习用户偏好（长期记忆）

## 📐 Prompt 四层结构（v1.0 当前）

```
┌────────────────────────────────────────────────────┐
│  Layer 0: 长期记忆块（build_memory_block）          │
│  来源：user_preferences + user_algorithm_history    │
│        + user_memories（Memory Curator 写入）       │
│  位置：拼到 system prompt 头部                      │
├────────────────────────────────────────────────────┤
│  Layer 1: System Prompt                             │
│  路径：shared/prompts/system/v1.txt                 │
│  内容：硬性约束 + 风格指南 + 节点身份说明           │
│       （Coder / Reviewer / Script Designer 各有版本）│
├────────────────────────────────────────────────────┤
│  Layer 2: Few-shot 召回（retriever）                 │
│  来源：few_shots 表（embedding + 关键词 fallback）  │
│  数量：top-2                                        │
│  入库：用户「👍 收藏为范例」按钮 / 手动 POST        │
├────────────────────────────────────────────────────┤
│  Layer 3: User Prompt                               │
│  首次：用户原始输入                                 │
│  refine：[历史用户指令 cap 6] + [上一版代码]         │
│          + [本次用户调整]                           │
│  reviewer：code + previous_feedback                  │
└────────────────────────────────────────────────────┘
```

## 📜 System Prompt 真相

**真实位置**：[`shared/prompts/system/v1.txt`](../../shared/prompts/system/v1.txt)

**核心要点**：
- 角色：ThinkCanvas 动画代码生成助手
- 接收中 / 英 prompt
- **强制 JSON 输出**：`{"thought": "...", "code": "..."}`
- 硬性约束（7 条）：import 限制 / 类结构 / 命名 / 无 LaTeX / 无 IO / 无循环炸弹 / 自包含
- 风格指南：黑底 / `BLUE` `YELLOW` `GREEN` `RED` / `rate_func=smooth` / `to_edge` 留白 / 总时长 < 30s
- **节点身份版本**：
  - Coder：直接生成代码
  - Reviewer：审查代码 → `CodeReview(ok, feedback)`
  - Script Designer：出 `SceneScript(title, concept, scenes[])`

## 💾 长期记忆块（v1.0 P3 新增）

```python
# app/agents/memory.py
async def build_memory_block(session, user_id) -> str:
    prefs = await user_preferences_dao.get(user_id)
    algos = await user_algo_history_dao.recent(user_id, limit=5)
    memories = await user_memories_dao.top_k(user_id, k=10)
    return compose_memory_block(prefs, algos, memories)
```

拼到 system prompt 头部，例：

```
[User Profile]
- default_style: 3b1b
- language: zh
- preferred_scene_count: 3-5

[Recent Algorithms]
- bubble_sort (3 天前) ✅
- binary_search (上周) ✅

[Long-term Memories]
- (preference) 用户偏好深色高对比度配色
- (fact) 上次问过傅里叶变换的频谱表示
- (feedback) 傅里叶那次希望加强左右双轴对比
```

Coder / Reviewer / Script Designer 三个节点都能看到。

### Memory Curator 提取

每条 conversation 跑完后异步调 `MemoryCurator.analyze_run()`：
- 输入：本轮 `prompt / code / status / error / feedback`
- LLM 输出：`MemoryEvent(kind, content, importance)` × 0-N
- 批量写 `user_memories` 表
- `importance` < 阈值的不写（避免噪声）

## 🎓 Few-shot 库（v1.0 当前）

### 现状

| 来源 | 状态 | 位置 |
|---|---|---|
| 硬编码嵌 system prompt | ❌ 已废弃 | `shared/prompts/styles/*.md` 空目录 |
| 冒泡排序 few-shot | ❌ 已从 system 移除 | 入库时用户「👍 收藏」自动写 few_shots |
| 用户自积累 | ✅ 主流 | `few_shots` 表 + embedding |

### 入库流程

```
[1] 用户生成完代码 + 视频
   ↓
[2] 前端显示「👍 收藏为范例」按钮
   ↓
[3] 用户点 → POST /api/v1/few_shots {prompt, code, style}
   ↓
[4] 后端
   ├─ 调 LLM 生成 summary（1-2 句话）
   ├─ embed_one_async(summary) 算 BGE-small-zh 向量（dim=512）
   └─ 写 few_shots 表
```

### 召回流程

```
[1] 创建会话 / 跑 agent 前
   ↓
[2] retriever.retrieve_similar_summaries(prompt, style, top_k=2)
   ├─ embed(prompt) 算向量
   ├─ pgvector 相似度检索（同 style 范围）
   ├─ 命中：返 top-2
   └─ 0 命中：fallback 到 recency 排序
   ↓
[3] 拼到 system prompt 末尾（few-shot 块）
```

**fallback 策略**：embedding 缺失时按 `created_at desc` 取最近 2 条。

## 🧪 校验流水线（实际）

实现位置：[`backend/app/tools/validator.py`](../../backend/app/tools/validator.py)

校验顺序：
1. 必须的 import（`from manim import *`）
2. 危险模式黑名单（正则）：
   - `open(` / `os.` / `sys.` / `subprocess.` / `shutil.`
   - `requests` / `urllib` / `http.`
   - `eval` / `exec` / `compile`
   - `while True:`
3. AST 解析无 `SyntaxError`
4. 必须存在 `Scene` 子类 + `construct()` 方法
5. Coder 内部 `invoke_with_recovery` 调 4 层兜底（详见 [workflow-design.md §Coder Agent](workflow-design.md)）

返回 `(ok: bool, error: str)`。

## 🔁 错误重试策略（v1.0 当前）

### Coder 内部 4 层兜底

实现位置：[`backend/app/agents/agent_recovery.py::invoke_with_recovery`](../../backend/app/agents/agent_recovery.py)

| 层 | 触发条件 | 行为 |
|---|---|---|
| 1 | LLM 输出在 thinking 块 | 提 thinking 块后重解析 |
| 2 | 输出无 `from manim import` | aggressive scan 找代码栅栏 |
| 3 | 仍失败 | 1-shot retry（带「重新输出代码」指令） |
| 4 | 还失败 | fallback + 报错（前端失败状态） |

### Reviewer 失败

Supervisor 条件边：reviewer 不通过 → 把 feedback 写进 `previous_feedback` → coder 续跑，最多 `MAX_CODE_ROUNDS` 轮。

```python
# app/agents/supervisor.py
def _route_after_reviewer(state) -> Literal["coder", "__end__"]:
    review = state["review"]
    if review is None or review.ok or state["code_round"] >= MAX_CODE_ROUNDS:
        return "__end__"
    return "coder"  # ⚠️ 只返 string，返 dict 会让 LangGraph 炸
```

### 渲染失败

`render_manim_dryrun` tool 失败时把 stderr 回喂 Coder，Coder 改代码重试。

`render_code`（真渲染，路由层调）失败时 `mark_render_failed(message_id, error)` 写库 + SSE 推 failed。

## 🧠 Script Designer Prompt（v1.0 P3 新增）

入口分诊 + 出脚本是两个独立 LLM 调用。

### 入口分诊

```
SCRIPT_DESIGNER_SYSTEM_DECISION_PROMPT（app/agents/supervisor.py）
判断 need_script（true / false）— LLM 输出 ScriptDecision JSON
```

判定标准：
- ✅ true：概念抽象 / 用户没明确步骤 / 内容长 / 风格未明说
- ❌ false：明确单一算法 / 用户给了具体步骤 / 调整现有动画

### 脚本生成

```
build_script_designer_prompt()（app/agents/script_designer.py）
输出 SceneScript Pydantic JSON：
{
  "title": "...",
  "concept": "...",
  "scenes": [
    {
      "index": 0,
      "duration_sec": 7,
      "description": "屏幕分成左右两栏...",
      "animation": "先淡入左右两根坐标轴...",
      "text_overlays": ["f(t) 时域", "F(ω) 频域"],
      "math_objects": ["NumberAxis", "FunctionGraph"]
    },
    ...
  ],
  "total_duration_sec": 28,
  "style": "3b1b"
}
```

前端 `ScriptReviewPanel` 渲染这个 JSON 让用户确认/拒绝/调整。

## 📊 Prompt 调优（实测经验）

| 经验 | 现状 |
|---|---|
| 中文 prompt 优于英文 | ✅ 经验证，MiniMax-M3 中文理解更稳 |
| 硬性约束 7 条不能省 | ✅ 删任何一条成功率↓ |
| few-shot 数量 1-2 个最佳 | ✅ 3+ 反而干扰 |
| Reviewer prompt 要明确 "ok 标准" | ✅ 否则 LLM 倾向打回 |
| Script Designer 提示词要 "3-5 镜" | ✅ 太多 / 太少都不自然 |
| 长期记忆 importance < 0.3 不写 | ✅ 避免噪声淹没有用记忆 |

## 🚀 演进路径

| 版本 | Few-shot 策略 | 记忆策略 | Reviewer |
|---|---|---|---|
| v1.0 早期 | 1 个硬编码 | 无 | 无 |
| **v1.0 当前** | `few_shots` 表 + embedding 召回 top-2 | user_prefs + user_algo_history + user_memories | LangGraph Reviewer 节点 |
| v1.x | + 主动种子（10 个高质量算法 few-shot） | + 跨设备同步 | + Reviewer 调优 |
| v2.x | + 用户自标记偏好 | + 视觉记忆（截图） | + Multi-Reviewer |

## ❓ 待验证

- [ ] Script Designer 在中长 prompt（300+ 字）下的稳定性
- [ ] Memory Curator 提取的 importance 阈值最优值
- [ ] 长期记忆块大小对 token 成本的影响
- [ ] Reviewer 失败时的 feedback 注入位置（system vs user）

## 🔗 相关文档

- Agent 节点细节 → [docs/workflow-design.md](workflow-design.md)
- 系统架构 → [docs/architecture.md](architecture.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 范围与里程碑 → [docs/mvp-scope.md](mvp-scope.md)
