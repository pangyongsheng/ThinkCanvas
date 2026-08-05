# 02 · MVP / v1.0 范围

> ⚠️ 下方 `v0.1` 一节作为历史参考保留；**当前 v1.0 共识以 [product.md](product.md) 为准**，下方「🆕 v1.0 开发步骤」为本文件唯一活跃里程碑。

---

## 🆕 v1.0 开发步骤（共识稿，6 步大方向）

> 与 [product.md](product.md)（战略与目标）、[tech-stack.md](tech-stack.md)（技术地图）配套使用。
> 每步独立可测，按序推进。

1. **基建联通** —— Next.js + FastAPI + Postgres + Redis + RQ Worker 跑通
   - 完成标志：空页面能开，Worker 能消费队列
   - **状态**：✅ 完成。Next 15 + FastAPI + Postgres + 后端最小 hello + 接 Postgres 接前端链路全跑通；Redis 起了但还没接业务。
2. **Code 流水线** —— MiniMax-M3 接入 + AST 校验 + 错误重试 + 3 算法手写高质量 few-shot
   - 完成标志：CLI 能输出可执行代码
   - **状态**：✅ 部分完成。LLM client 接通；`POST /generate` 单轮 + 简单重试；`/generate/agent` 跑 LangGraph 标准 ReAct（langgraph.prebuilt.create_react_agent）。3 算法 few-shot：**只写了冒泡排序 1 个**。
3. **渲染流水线** —— subprocess + 资源限制 / 沙箱 + 产物落盘
   - 完成标志：CLI 能输出 mp4
   - **状态**：✅ 完成。subprocess + 60s timeout；产物落 `./media/`；`/media` 静态文件挂载。LaTeX 没装时 MathTex 报错。
4. **Web UI 最小版** —— 输入 / 进度（百分比 + 节点）/ 视频 / 代码 / 重渲染
   - 完成标志：Web 端到端跑通
   - **状态**：✅ 基本版。输入 / Generate 按钮 / 进度条 / 视频 / 代码框 / 重渲染 / SSE 实时进度。全跑通。
5. **持久化 + 多语言 + 可观测** —— user / history 表 + 中英切换 + LangSmith 接入
   - 完成标志：刷新页面历史还在；UI 切语言立刻反应
   - **状态**：❌ 没动。
6. **端到端验证** —— 3 个算法各跑 10 次，记录成功率 / 时长 / 修整
   - 完成标志：数据说话、可继续推进 v1.x
   - **状态**：❌ 没动。

---

## 🤖 Agent / LangChain 学到的（截至本对话）

| 模式 | 实现位置 | 状态 |
|---|---|---|
| **结构化输出**（强制 JSON `{thought, code}`） | `app/agents/coder.py::_parse_react_response` | ✅ 有 test 覆盖 |
| **ReAct 反思 + 错误回喂**（手写版） | `app/agents/coder.py::CoderAgent` | ✅ 4 test 通过 |
| **LangGraph 标准 ReAct** | `app/agents/react_coder.py` 用 `langgraph.prebuilt.create_react_agent` | ⚠️ 代码就位，**未实测** MiniMax 是否真返回 `tool_calls` |
| **@tool 装饰器** | `app/agents/tools.py`（`validate_manim_code` / `render_manim_dryrun`） | ✅ 学习样本 |
| **HTTP → Agent 分层** | `app/api/v1/generate.py` 只调 `agent.run()`；agent 在 `app/agents/` | ✅ |

### ⚠️ 已知问题（下一个模型应注意）

1. **MiniMax 的 OpenAI 兼容 API 对 `tool_calls` 支持不明**。直接 `bind_tools()` 测过一次 LLM 没返回 tool_calls（陷入"全文字"模式）。LangGraph 版本目前还没实战验证。
2. **few-shot 只有 1 个**（冒泡排序）；v1.0 范围要求的另外 2 个（二分查找、图 BFS 遍历）没写。
3. **Redis 接了 docker 但没接业务**（任务队列层是空的——所有逻辑当前 in-process 完成）。
4. **CORS / 项目根 .env / `SecretStr` / StructuredOutput 修复点**散落在这次 session 里，没整理到一个 PR-ready commit。
5. **真正的 LangChain 链路没建对**：用户原始诉求是"学习 LangChain 项目"，当前实现多数是手写 loop。**下一个接手的人应该把 `app/agents/coder.py::CoderAgent` 重写成 LangGraph 标准 `StateGraph` 节点**（function-based or class-based），让 agent loop 真正由 LangGraph 状态机驱动。

---

## 🗂 关键文件清单（接手请扫这些）

```
backend/
├── app/
│   ├── agents/
│   │   ├── coder.py           # 手写 CoderAgent（仓库主 agent）
│   │   ├── react_coder.py    # LangGraph create_react_agent 版本（基本框架，没实战）
│   │   └── tools.py           # @tool 装饰的 validate_manim_code / render_manim_dryrun
│   ├── api/v1/
│   │   ├── generate.py       # /generate (sync), /generate/stream (SSE), /generate/agent
│   │   ├── render.py         # /render (单进程渲染)
│   │   ├── health.py
│   │   └── readyz.py
│   ├── renderers/manim.py    # subprocess + 60s 超时
│   ├── tools/validator.py    # AST + 危险模式 + Scene 子类检查
│   ├── llm/client.py         # ChatOpenAI 配 MiniMax base_url
│   ├── config.py             # 读项目根 .env，model_name = "MiniMax-M3"
│   └── main.py
├── tests/agents/
│   └── test_coder.py         # 4 个测试全过（手写版 agent）
├── pyproject.toml
└── .env.example

shared/prompts/system/v1.txt    # JSON 强约束输出 format

frontend/
├── app/page.tsx               # EventSource 订阅 + 进度条
├── lib/api.ts                 # generateCode / renderManim / subscribeGenerate
└── ...

docker/docker-compose.yml      # postgres + redis 已起
```

---

## 🔑 下一步建议（接手者）

1. **最优先**：用 `langgraph.StateGraph` 重写 `app/agents/coder.py` 的 loop（不要手写）
2. **其次**：补完 few-shot 库（二分查找、图 BFS 遍历）
3. **再然后**：Step 5 持久化（user / history 表 + alembic 迁移）
4. **最后**：Step 6 端到端 3 算法 × 10 次跑

---

## ✅ v0.1 必须做（历史参考）

### 1. Web 前端（薄薄一层）
- 文本框输入 prompt（多行）
- "生成" 按钮
- 进度条 / 状态展示
- 视频播放器 + 下载按钮
- 历史记录（**本地的就行**，不需要登录）

### 2. 后端 API
- `POST /api/generate` — 提交任务
- `GET /api/task/:id` — 查询状态
- `GET /api/video/:id` — 拿视频文件
- `WS /ws/task/:id` — 实时推送进度

### 3. LLM 生成
- 默认模型：**DeepSeek-V3**（通过 OpenAI 兼容 API）
- 输出：纯 Python 代码，无 Markdown 包裹
- **必填校验**：
  - 包含 `from manim import *`
  - 包含 `class X(Scene)`
  - 包含 `def construct(self)`
  - AST 解析无语法错误
- **错误重试**：最多 2 次（带错误信息反馈给 LLM）

### 4. 渲染执行
- **沙箱**：subprocess + Docker（v0.1 简化版：subprocess + 资源限制 + 超时）
- **超时**：60 秒
- **资源限制**：CPU 1 核、内存 2GB
- **输出**：720p MP4

### 5. 种子算法库（Few-shot 用）
至少 **10 个**手工调好的算法动画，作为 Prompt 的 few-shot examples：

| 类别 | 算法 |
|---|---|
| 排序 | 冒泡排序、快速排序、归并排序 |
| 搜索 | 二分查找 |
| 数据结构 | 栈、队列、链表反转 |
| 树 | 二叉树 BFS、二叉树 DFS |
| 图 | BFS 遍历、DFS 遍历 |

## ❌ v0.1 明确不做

- ❌ 用户系统（登录、注册、付费）
- ❌ LaTeX 数学公式（用 Text() 代替，留 v0.2）
- ❌ 3D 图形
- ❌ 视频编辑/拼接
- ❌ 自定义风格（颜色、字体）
- ❌ 团队协作
- ❌ 多语言（先中文 UI）
- ❌ 公开 API / SDK
- ❌ 移动端优化

## 🎯 验收标准（Definition of Done）

### 功能性
- [ ] Web 页面打开可输入 prompt
- [ ] 输入"冒泡排序" → 30 秒内输出可看的 720p 视频
- [ ] 输入"二分查找" → 同上
- [ ] 输入"二叉树 BFS 遍历" → 同上
- [ ] 10 个种子算法全部能成功生成

### 质量
- [ ] 简单算法一次成功率 ≥ 70%
- [ ] 端到端 P95 延迟 < 90 秒
- [ ] 视频清晰度 720p、流畅（30fps）

### 工程
- [ ] 部署文档齐全
- [ ] 关键路径有日志
- [ ] 错误有友好提示
- [ ] API 文档自动生成

## 📊 成功指标

| 指标 | 目标 | 衡量方式 |
|---|---|---|
| 一次成功率 | ≥ 70% | 10 个种子 prompt 测试 |
| 平均生成时间 | < 60s | 统计 |
| 视觉质量（5分制） | ≥ 3.5 | 5 个内测用户评分 |
| 算法正确性 | 100% | 人工 review 10 个视频 |
| 视频可读性 | ≥ 3.5 | 5 个内测用户评分 |

## 🚧 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| DeepSeek 代码能力不够 | 中 | 高 | 多 few-shot；可切换 Qwen2.5-Coder |
| 渲染超时 | 高 | 中 | 限制 prompt 复杂度；引导用户简化 |
| 沙箱逃逸 | 低 | 高 | Docker 隔离 + 网络禁用 |
| 单次成本太高 | 中 | 中 | 限制重试次数；选性价比模型 |

## 🗓 建议里程碑

```
Week 1: 基础架构
  ├─ Day 1-2: FastAPI + Redis + Worker 骨架
  ├─ Day 3-4: DeepSeek 集成 + Prompt v1
  └─ Day 5-7: Manim 沙箱 + 渲染管线

Week 2: 端到端跑通
  ├─ Day 1-3: 10 个种子算法 few-shot
  ├─ Day 4-5: Web UI（最简版）
  └─ Day 6-7: 端到端联调

Week 3: 打磨
  ├─ Day 1-2: 错误处理 + 用户体验
  ├─ Day 3-4: 内测（找 5 个朋友）
  └─ Day 5-7: Bug fix + 文档
```
