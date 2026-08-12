# 02 · 系统架构

> 反映 v1.0 **当前**实际状态（2026-08 更新）。所有路径、组件、命令以仓库代码为准。
>
> 关键演进：v1.0 早期是"标准 `create_agent` + 单 agent + SSE 流"，v1.0 P2 起升级为 **LangGraph `StateGraph` Supervisor**（Coder ↔ Reviewer + 入口分诊 + Script Designer），并加了**长期记忆 / Memory Curator / 持久化中间件**。

## 🏗 整体架构（v1.0 当前）

```
┌──────────┐    ┌──────────┐    ┌──────────────┐
│  Browser │───▶│  Next.js │───▶│   FastAPI    │───▶ Postgres
│  (用户)  │◀───│  Web UI  │◀───│   Backend    │◀──▶ (conversations
└──────────┘    └──────────┘    └──────┬───────┘     /messages/
      ▲               ▲                │              agent_steps/
      │               │                │              few_shots/
      │  SSE 实时进度  │ 静态文件       │              user_preferences/
      │               │  /media/*      │              user_algorithm_history/
      │               └────────────────│              user_memories)
      │                                │
      │                                ▼
      │                         ┌──────────────┐
      │                         │  Supervisor  │  LangGraph StateGraph
      │                         │   StateGraph │  ┌─ entry_router
      │                         └──────┬───────┘  ├─ script_decision
      │                                │          ├─ script_designer
      │                                ▼          └─ coder ↔ reviewer
      │                         ┌──────────────┐
      │                         │  LangChain   │  create_agent + middleware
      │                         │   Agent      │  ├─ AgentPersistenceMiddleware
      │                         └──────┬───────┘  └─ 工具: validate / render_dryrun
      │                                │
      │                                ▼
      │                         ┌──────────────┐
      │                         │  MiniMax-M3  │ via langchain-litellm
      │                         └──────────────┘
      │
      │
      ▼
   /media/*  ←  Manim 渲染产物（FastAPI StaticFiles）
```

## 🔄 数据流（v1.0 当前 — 端到端）

### 首次生成（`POST /conversations`）

```
[1] 用户输入 prompt（前端 8000 等 style）
   ↓
[2] 前端 POST /api/v1/conversations (SSE)
   ↓
[3] FastAPI 路由处理
   ├─ _resolve_user_id（X-User-Id 中间件）
   ├─ few-shot 召回（retriever，pgvector + BGE）
   ├─ 长期记忆块拼装（user_preferences + user_algorithm_history + user_memories + feedbacks）
   ├─ AgentService.run_initial(phase=scripting)
   │   ├─ 创建 conversation + user message
   │   ├─ AgentPersistenceMiddleware.before_agent 建 assistant 壳
   │   ├─ Supervisor.ainvoke(phase=scripting)
   │   │   ├─ entry_router → script_decision
   │   │   ├─ script_decision → script_designer (LLM 决策 need_script)
   │   │   ├─ need_script=true → script_designer 出 SceneScript JSON
   │   │   │                  → __end__（等用户确认）
   │   │   └─ need_script=false → coder（直接生成代码）
   │   ├─ Middleware 自动落 agent_steps + finalize assistant message
   │   └─ Memory Curator 异步：分析本次 run，写入 user_memories
   │
   ├─ phase=scripting → SSE 推 script_ready + done（前端弹脚本面板）
   └─ phase=coding → 渲染（render_code）→ SSE 推 done（前端显示视频）
```

### 脚本确认（`POST /conversations/{id}/confirm`）

```
[1] 用户点「确认并生成」
   ↓
[2] 前端 POST /api/v1/conversations/{id}/confirm (同步)
   ↓
[3] FastAPI
   ├─ AgentService.run_after_confirm(phase=coding)
   │   ├─ 校验 conv.phase == "scripting"
   │   ├─ set_phase(coding)
   │   ├─ Supervisor.ainvoke(phase=coding)
   │   │   ├─ entry_router → coder（跳过 script_decision / designer）
   │   │   └─ coder ↔ reviewer 循环直到 reviewer.ok 或 code_round >= MAX
   │   └─ middleware finalize
   ├─ render_code → to_video_url
   ├─ attach_video(message_id, video_url, duration_sec)
   └─ 响应 {code, scene_name, video_url, duration_sec, conversation_id}
```

### 多轮调整（`POST /conversations/{id}/refine`）

```
[1] 用户输入调整指令
   ↓
[2] 前端 POST /api/v1/conversations/{id}/refine (SSE)
   ↓
[3] FastAPI
   ├─ 追加 user message
   ├─ AgentService.run_refine
   │   ├─ _build_refine_prompt（[历史用户指令 cap 6] + [上一版完整代码] + [本次用户调整]）
   │   ├─ Supervisor.ainvoke(phase=coding)
   │   │   └─ coder ↔ reviewer
   │   └─ middleware finalize
   └─ 渲染 → SSE 推 done
```

## 🧱 实际模块结构（v1.0 当前）

```
backend/app/
├── main.py                              # FastAPI 入口；CORS + 静态 /media
├── config.py                            # 读项目根 .env；model_name="MiniMax-M3"
├── agents/
│   ├── builder.py                       # build_agent 工厂（lru_cache 单例）
│   ├── supervisor.py                    # ⭐ LangGraph StateGraph Supervisor
│   │   ├── entry_router (phase=scripting/coding/done)
│   │   ├── _script_decision_node (LLM 决策 need_script)
│   │   ├── _script_designer_node (结构化 SceneScript)
│   │   ├── _make_coder_node (单 agent + invoke_with_recovery)
│   │   ├── _reviewer_node (CodeReview LLM)
│   │   └── _route_after_reviewer (string only — dict 会让 LangGraph 炸)
│   ├── script_designer.py               # SceneScript Pydantic + 提示词
│   ├── reviewer.py                      # build_reviewer_llm + CodeReview schema
│   ├── memory.py                        # build_memory_block — 偏好/历史/反馈
│   ├── memory_curator.py                # ⭐ MemoryCurator — 异步分析 + 写 user_memories
│   ├── algorithm_extractor.py           # extract_algorithm_name — 写 user_algorithm_history
│   ├── agent_recovery.py                # 4 层兜底（thinking / aggressive / fence + 1-shot retry）
│   ├── summarizer.py                    # few-shot 摘要生成
│   ├── retriever.py                     # few-shot 召回（embedding + 关键词 fallback）
│   ├── styles.py                        # 3 风格注册（academic / 3b1b / minimal）
│   ├── tools.py                         # @tool validate_manim_code / render_manim_dryrun
│   ├── schemas.py                       # CodeOutput / CodeReview / SceneScript
│   ├── prompts.py                       # 提示词拼装
│   ├── service.py                       # AgentService（路由层唯一编排入口）
│   ├── dao/                             # ⭐ 数据访问层（按表拆文件）
│   │   ├── conversations.py
│   │   ├── messages.py
│   │   ├── agent_steps.py
│   │   └── ...
│   └── middleware/
│       └── persistence.py               # ⭐ AgentPersistenceMiddleware（统一持久化入口）
├── api/v1/
│   ├── conversations.py                 # ⭐ /conversations + /refine + /confirm
│   ├── few_shots.py                     # /few_shots CRUD + embedding
│   ├── preferences.py                   # /preferences 用户偏好
│   ├── feedback.py                      # /feedback 收藏为范例
│   ├── memories.py                      # /memories 长期记忆
│   ├── health.py
│   └── readyz.py
├── renderers/manim.py                   # subprocess + 60s 超时
├── tools/validator.py                   # AST + 危险模式 + Scene 子类检查
├── llm/client.py                        # ChatLiteLLM 封装为 ChatOpenAI
├── embeddings.py                        # BGE-small-zh + 异步 batch
└── db/
    ├── session.py                       # async_session_factory
    └── models/
        ├── user.py
        ├── conversation.py              # 含 phase + current_script JSONB
        ├── message.py
        ├── agent_step.py                # 节点级 trace
        ├── few_shot.py                  # 摘要 + embedding
        ├── user_preference.py
        ├── user_algorithm_history.py
        ├── user_memory.py               # ⭐ 长期记忆
        └── feedback.py

shared/prompts/
├── system/v1.txt                        # System prompt（硬性约束 + 风格指南）
└── styles/                              # 3 风格补充

frontend/
├── app/page.tsx                         # ⭐ 3 栏布局 + 脚本面板 + SSE 订阅
└── lib/
    ├── api.ts                           # fetchJson + 类型
    └── user.ts                          # ULID + localStorage
```

## 📝 关键决策记录 (ADR)

### ADR-001 · 默认 LLM = MiniMax-M3（LiteLLM 适配层）
- 同 v1.0 早期，未变。

### ADR-002 · 同步渲染，不上 Worker（v1.0 简化）
- 同 v1.0 早期。**v1.x TODO**：rq.enqueue 解 API 阻塞。

### ADR-003 · SSE 替代 WebSocket
- 同 v1.0 早期。

### ADR-004 · ManimCE 而非 ManimGL
- 同 v1.0 早期。

### ADR-005 · 标准 LangChain 1.x `create_agent` + LiteLLM 适配层
- 仍生效；Coder 内部继续用 `create_agent` + `invoke_with_recovery`。

### ADR-006 · 匿名 ULID 用户
- 同 v1.0 早期。

### ADR-007 · 双 agent 路径合一
- 仍生效；P3 起加 Script Designer / Reviewer 也走同一 `build_agent` 工厂。

### ADR-008 · LangGraph `StateGraph` Supervisor（Coder ↔ Reviewer + 入口分诊 + Script Designer）（2026-08 P2/P3）
- **决策**：v1.x 把单 agent 升级为 LangGraph `StateGraph`，节点 = Script Designer / Coder / Reviewer，条件边控制 routing；Coder 仍是 `create_agent` 单例（reuse factory），Supervisor 只在外层加编排
- **理由**：
  - P2 Reviewer 节点：能 catch Coder 自检漏掉的边界 case（API 错误、AST 黑名单外但语义错）
  - P3 Script Designer：复杂 / 抽象 prompt 先出脚本给用户确认 → 一次成功率↑ + 用户不被黑盒
  - 入口分诊：明确指令直接走 Coder，省一次 LLM
- **条件边硬性规则**（防回归）：router 函数必须只返 `str`（`Literal["coder", "__end__"]`）— **返 dict 会让 LangGraph `TypeError: cannot use 'dict' as a dict key`**
- **代价**：StateGraph 不可调试性比单 agent 差，依赖可视化（`g.draw_mermaid()` 出图）

### ADR-009 · LangChain 官方 Middleware 统一 Agent 持久化（2026-08 重构）
- **决策**：所有 agent 运行追踪（agent_steps / assistant message 自动 finalize）走 LangChain 1.x 官方 `AgentMiddleware`，不再在路由层手写埋点
- **理由**：
  - 路由层只做 HTTP 调度，业务零侵入
  - 中间件一处实现，所有 agent 入口（`run_initial` / `run_after_confirm` / `run_refine`）自动生效
  - 解耦：DB 操作在 `agents/dao/`，中间件只调 DAO，不直接写 SQL
- **架构**：
  ```
  API 路由 (FastAPI)
    └─ AgentService.run_*(...)
         └─ supervisor.ainvoke(...)
              └─ create_agent(..., middleware=[AgentPersistenceMiddleware])
                   └─ AgentPersistenceMiddleware.before_agent / after_agent
                        └─ AgentStepsDAO / MessagesDAO
  ```
- **单行依赖方向**：Web → Agent → DAO；DAO 不知道上层存在。

### ADR-010 · 长期记忆 + Memory Curator（2026-08 P3）
- **决策**：每条 conversation 跑完后异步调 `MemoryCurator` 分析这次 run 提取长期记忆，存 `user_memories` 表
- **schema**：`user_memories(user_id, kind, content, importance, source_conversation_id, created_at)`，kind ∈ {preference, fact, algorithm, feedback}
- **召回**：`build_memory_block` 拼到 system prompt 头部，按 user 召回 top-N
- **异步**：在 `agent.run` 完成后 fire-and-forget，不阻塞响应
- **理由**：跨会话持续学习用户偏好（风格、难度、关注点）→ 一次成功率↑

### ADR-011 · few-shot 检索替代硬编码（2026-08）
- **决策**：`shared/prompts/styles/*.md` 里硬编码 few-shot **全部废弃**；改为 `few_shots` 表 + embedding（BGE-small-zh, dim=512）+ retriever 按相似度召回 top-2
- **理由**：用户能"👍 收藏为范例"自己积累库；retriever 自动按 prompt 匹配
- **fallback**：embedding 缺失时按 recency 兜底
- **后台**：`POST /api/v1/few_shots` 入库时同步调 `embed_one_async` 算 embedding

## 🛡 分层硬性规范（2026-08 强化）

> 之前几轮重构反复出问题，固化为规范：

1. **Web 层**（`app/api/v1/`）只做 HTTP 接收 / 鉴权 / 调 AgentService / 渲染 / 响应 — **不允许写 agent 业务逻辑、DB 操作、prompt 拼装**
2. **Agent 层**（`app/agents/`）只做业务编排 — **不允许写 FastAPI 路由、Pydantic Out schema**（schema 走 `app/schemas/` 或在 `app/api/v1/` 内部）
3. **DAO 层**（`app/agents/dao/`）只做单表 CRUD — **不允许写跨表业务**
4. **Middleware**（`app/agents/middleware/`）只做业务中转 — 调 DAO 方法，不直接写 SQL
5. **依赖方向单向**：Web → Agent → DAO，DAO 不知道上层

## 🚨 安全考虑

| 风险 | 缓解 | 状态 |
|---|---|---|
| 死循环 | subprocess timeout=60s | ✅ |
| 删文件 / 网络请求 | AST 黑名单（`open` / `os.` / `requests` 等）| ✅ |
| 内存炸弹 | ulimit | ❌ |
| Docker 隔离 | v0.2 引入 | ❌ |
| Prompt 注入 | system prompt 硬性约束 + few-shot 风格示范 | ✅ |

## 🔗 相关文档

- 范围与里程碑 → [docs/mvp-scope.md](mvp-scope.md)
- 工作流与 Agent 设计 → [docs/workflow-design.md](workflow-design.md)
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 启动命令 → [docs/quickstart.md](quickstart.md)
