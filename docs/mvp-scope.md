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
   - **状态**：✅ **已完成（2026-08 升级）**。LiteLLM 适配层接通 MiniMax；标准 LangChain 1.x `create_agent(model=, tools=, system_prompt=, response_format=CodeOutput)` 取代手写 agent loop（手写 LCEL chain / JSON parser / 工具循环全部删除）；3 算法 few-shot：**只写了冒泡排序 1 个**（仍欠 2 个）。
3. **渲染流水线** —— subprocess + 资源限制 / 沙箱 + 产物落盘
   - 完成标志：CLI 能输出 mp4
   - **状态**：✅ 完成。subprocess + 60s timeout；产物落 `./media/`；`/media` 静态文件挂载。LaTeX 没装时 MathTex 报错。
4. **Web UI 最小版** —— 输入 / 进度（百分比 + 节点）/ 视频 / 代码 / 重渲染
   - 完成标志：Web 端到端跑通
   - **状态**：✅ 基本版。输入 / Generate 按钮 / 进度条 / 视频 / 代码框 / 重渲染 / SSE 实时进度。全跑通。
5. **持久化 + 用户系统** —— users 表 + 匿名 ULID 身份 + conversations 隔离；偏好 / 历史召回留 v1.1
   - 完成标志：刷新页面历史还在；不同 ULID 看不到对方会话
   - **状态**：✅ 基本完成（2026-08）。users 表 + X-User-Id 中间件 + 前端 ULID；中英切换留待 v1.1。

6. **端到端验证** —— 3 个算法各跑 10 次，记录成功率 / 时长 / 修整
   - 完成标志：数据说话、可继续推进 v1.x
   - **状态**：❌ 没动。

## 🆕 v1.1 增量（2026-08-06 起）

> v1.0 的 6 步基线已大部分跑通。v1.1 在它上面加深度，不是新立项目。

### v1.1.1 · 多轮对话（已上线）
- Conversations + Messages 双表
- refine prompt 三段：[历史用户指令]（最近 6 条 user 原话）+ [上一版完整代码] + [本次用户调整要求]
- 助手的旧回复**不喂**（省 token、且历史 user 原话足够表达渐进式需求）
- UI 全部收敛到右侧对话面板（首次生成 + 续轮调整）

### v1.1.2 · 用户系统（已上线）
- 匿名 ULID：前端 `localStorage` 存 26 位 Crockford 字符串，发请求带 `X-User-Id` header
- 服务端 `UserIdMiddleware`：合法则用，缺失/非法回落 `ANON_USER_ID`
- 所有 conversations 强制 `user_id NOT NULL`（外键到 users，ondelete CASCADE）
- 历史数据迁移：把已有 conversations 全塞给 `ANON_USER_ID`，不丢数据
- 不做：账号、密码、登录、token、多设备同步

### v1.1.3 · 编码规范化（已上线）
- 单文件 ≤ 300 行（公开 helper 模块 ≤ 400 行），超出拆 helper
- 整个 `app/agents/` docstring 改中文
- `state.py` → `schemas.py`（避免和 LangChain `StateGraph` 撞名）
- `react_coder.py` 删死别名；`refine.py` 改走 `build_agent(extra_system_prompt=...)` —— 两个 agent 路径合一
- 完整规范见 `docs/coding-guidelines.md`

### v1.1.4 · 持久化记忆（TODO，明天）
- `user_preferences(default_style, language)` 表
- `user_algorithm_history(user_id, algorithm, last_used_at)` 表
- 创建会话时按 user 偏好 / 过去用过的算法塞 system prompt 头部

### v1.1.5 · Few-shot 检索（TODO，明天）
- 把 `shared/prompts/styles/*.md` 里硬编码的 few-shot 抽到 `few_shots` 表
- 按 prompt 关键词粗筛 1-2 个拼进 system prompt
- 目标：抬升一次成功率

### v1.1.6 · 端到端压测（TODO）
- 3 算法 × 10 次，记录成功率 / 时长 / 修整

---

## 🤖 Agent / LangChain 学到的（截至 2026-08 重构）

| 模式 | 实现位置 | 状态 |
|---|---|---|
| **LiteLLM 适配层** | `app/llm/client.py::ChatLiteLLM` 封装为 `ChatOpenAI` | ✅ 业务只见 `ChatOpenAI` |
| **结构化输出**（`CodeOutput` Pydantic schema） | `app/agents/state.py::CodeOutput` + `create_agent(response_format=...)` | ✅ 6 test 通过 |
| **标准 LangChain 1.x `create_agent`** | `app/agents/builder.py` 调用 `langchain.agents.create_agent` | ✅ 单例，lru_cache(style_id, extra_prompt) |
| **四层兜底**（thinking / 字符串扫描 / 代码栅栏 + 1-shot retry） | `app/agents/agent_recovery.py::invoke_with_recovery` | ✅ MiniMax-M3 频繁只输出 thinking |
| **多轮对话 prompt 拼装** | `app/agents/refine.py::_build_refine_prompt` | ✅ 历史用户指令 cap 6 条 |
| **`@tool` 装饰器** | `app/agents/tools.py`（`validate_manim_code` / `render_manim_dryrun`） | ✅ agent 直接调用 |
| **HTTP → Agent 分层** | `app/api/v1/generate.py` 只调 `run_agent()`；agent 在 `app/agents/builder.py` | ✅ |
| **可观测性** | `app/core/logging.py` + `run_agent` 进出日志 + FastAPI 全局异常中间件 | ✅ |

### ⚠️ 已知问题（下一个模型应注意）

1. ~~MiniMax 不支持 `tool_calls`~~ → **已解决**：用 LiteLLM 内嵌归一化，业务层标准 LangChain 写法。详见 [docs/session-summary.md](session-summary.md#session-2-litellm-适配层--标准-langchain-1x-重构2026-08-06)。
2. **LiteLLM 链路偶发 Connection error**：MiniMax 自身稳定性问题；需要补 tenacity 重试层（v1.x TODO）。
3. **few-shot 只有 1 个**（冒泡排序）；v1.0 范围要求的另外 2 个（二分查找、图 BFS 遍历）没写。
4. **Redis 接了 docker 但没接业务**（任务队列层是空的——所有渲染当前 in-process 完成）。
5. **手写 loop 已清理**：`coder/` 子目录 6 个文件全部删除；`create_react_agent` 不再使用。

---

## 🗂 关键文件清单（接手请扫这些）

```
backend/app/
├── main.py                              # FastAPI 入口；挂 UserIdMiddleware + CORS
├── config.py                            # 读项目根 .env
├── middleware/user_id.py                # X-User-Id 解析（case-insensitive ULID 正则）
├── agents/
│   ├── react_coder.py                   # run_agent 薄壳（39 行）
│   ├── refine.py                        # run_refine（拼 user history）
│   ├── builder.py                       # create_agent 工厂 + lru_cache(style_id, extra_prompt)
│   ├── schemas.py                       # CodeOutput Pydantic schema
│   ├── styles.py                        # 3 风格注册（academic / 3b1b / minimal）
│   ├── tools.py                         # @tool validate_manim_code / render_manim_dryrun
│   └── agent_recovery.py                # 四层兜底（thinking / aggressive / fence + retry）
├── api/v1/
│   ├── generate.py                      # /generate (legacy) + /generate/stream (主用)
│   ├── conversations.py                 # /conversations + /refine SSE；5 个端点都按 user_id 隔离
│   ├── tasks.py                         # 老 task CRUD（v2 移除）
│   ├── render.py
│   ├── health.py
│   └── readyz.py
├── storage/
│   ├── conversations.py                 # CRUD + sync helpers（测试用）
│   ├── users.py                         # upsert_user / touch_last_seen
│   └── tasks.py
├── renderers/manim.py                   # subprocess + 60s 超时
├── tools/validator.py                   # AST + 危险模式 + Scene 子类检查
├── llm/client.py                        # ChatLiteLLM 封装为 ChatOpenAI
└── db/
    ├── session.py
    └── models/
        ├── user.py
        ├── conversation.py              # 含 user_id FK
        ├── message.py
        └── task.py

backend/alembic/versions/
├── 20260806_add_conversations_and_messages.py
└── 20260806_add_users_and_user_id.py    # users + conv.user_id + anon backfill

backend/tests/                            # 107 passed (2026-08-08)
├── conftest.py
├── agents/                               # agent_recovery / refine / coder
├── storage/                              # user history cap + user scope
└── middleware/                           # user_id 中间件

shared/prompts/styles/                    # base.md + 3b1b / minimal / academic

frontend/
├── app/page.tsx                          # 3 栏布局 + 乐观 user message
├── components/
│   ├── HistorySidebar.tsx                # 可折叠侧栏（默认 48px）
│   ├── CodeViewer.tsx                    # 视频 / 代码 tab（代码默认折叠）
│   └── ConversationPanel.tsx             # 对话气泡 + 输入框
└── lib/
    ├── api.ts                            # fetchJson 默认加 X-User-Id
    └── user.ts                           # ULID 生成 + localStorage 持久化

docker/docker-compose.yml                 # postgres + redis（redis 未接业务）
```

---

## 🔑 下一步建议（接手者，按优先级）

1. **持久化记忆**（`user_preferences` + `user_algorithm_history`，明天）：创建会话时按偏好 / 过去算法塞 system prompt 头部
2. **Few-shot 检索**（明天）：把 `shared/prompts/styles/*.md` 里硬编码的 few-shot 抽到 `few_shots` 表，按 prompt 关键词粗筛 1-2 个拼进 system prompt
3. **Step 6 端到端压测**：3 算法 × 10 次成功率 / 时长
4. **Worker 异步化**（v1.x）：`rq.enqueue` 解 API 阻塞
5. **死代码清理**：`/generate` legacy + `/generate/agent` 死端点（前端未用，等前端切完删）
6. **远期**：等加多 Agent 编排（v2.0）时评估 `langgraph.StateGraph`；当前 `create_agent` 单 agent 已够

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
