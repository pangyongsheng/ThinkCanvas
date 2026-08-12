# ThinkCanvas

> 输入文字，自动生成 3Blue1Brown 风格的 Manim 算法/数学动画视频。

让不会 Manim 的人，也能产出专业的算法可视化视频。

![status](https://img.shields.io/badge/status-active-success)
![python](https://img.shields.io/badge/python-3.14-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-186%20passed-brightgreen)

## ✨ 功能

| | |
|---|---|
| 🎬 **视频生成** | 文字 prompt → 完整 Manim 视频，720p / 60s timeout |
| 📜 **脚本确认** | 复杂 / 抽象 prompt 先出脚本给用户看，确认后再生成 |
| 🔁 **多轮调整** | 右侧对话面板说"换成红底"，自动重写代码 + 重渲染 |
| 👤 **个人身份** | ULID 匿名身份 + 历史和偏好自动保留（清浏览器 = 失忆）|
| 📚 **Few-shot 库** | 点"👍 收藏为范例"积累好例子，自动算 embedding 入库 |
| 🔍 **Few-shot 检索** | 按 prompt 相似度召回 top-2，缺数据 fallback recency |
| 🧠 **长期记忆** | 跨会话学用户偏好 / 算法历史 / 反馈，自动拼到 system prompt |
| 🤖 **多 Agent 编排** | LangGraph `StateGraph` Supervisor：入口分诊 + Script Designer + Coder ↔ Reviewer |
| 🪝 **统一持久化** | LangChain 官方 `AgentMiddleware` 一处钩子全局生效 |
| 🔌 **LLM 可插拔** | LiteLLM 把多厂商协议归一化，换厂商改一行 |
| 🛡 **多层兜底** | Coder 内部 4 道防线 + Reviewer 自检 + Recv Retry |
| 🏷 **结构化输出** | Pydantic `CodeOutput` / `CodeReview` / `SceneScript` 三套 schema |

## 🏗 架构（v1.0 当前）

```
┌──────────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js 15 + TS)                                           │
│  3 栏：左历史 / 中视频+代码+脚本面板 / 右对话面板                      │
│  EventSource 订阅 SSE，乐观 user message                             │
└──────────────────────────────────────────────────────────────────────┘
                              │ HTTP + X-User-Id
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ FastAPI (app/api/v1/) — 纯 Web 层：只接 HTTP / 鉴权 / 调 AgentService│
│  /conversations (SSE)  /refine (SSE)  /confirm (同步)                │
│  /few_shots  /preferences  /memories  /feedback                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ AgentService (app/agents/service.py) — 唯一编排入口                  │
│  run_initial / run_after_confirm / run_refine                        │
│  召回 few-shot → 拼长期记忆块 → 跑 supervisor                        │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LangGraph StateGraph Supervisor (app/agents/supervisor.py)           │
│                                                                      │
│   [__start__] → entry_router ─┬─ phase=coding → coder               │
│                               └─ phase=scripting → script_decision  │
│                                                       │              │
│                                            ┌──────────┴──────────┐   │
│                                            ▼                     ▼   │
│                                      script_designer          coder  │
│                                            │                     │    │
│                                            ▼                     ▼    │
│                                          __end__              reviewer │
│                                       (等用户确认)             │   │   │
│                                                              ok  feedback│
│                                                               │   │   │
│                                                          __end__  coder │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LangChain 1.x create_agent + AgentMiddleware                         │
│  Coder: validate_manim_code + render_manim_dryrun tools              │
│  AgentPersistenceMiddleware: before_agent 建壳 / after_agent 落库   │
│  invoke_with_recovery: 4 层兜底（thinking / aggressive / fence+retry）│
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ MiniMax-M3 (via langchain-litellm.ChatLiteLLM 封装为 ChatOpenAI)     │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ DAO 层 (app/agents/dao/) — 单表 CRUD                                  │
│  ConversationsDAO / MessagesDAO / AgentStepsDAO / FewShotsDAO / ...   │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Postgres (10+ 表)                                                    │
│  users / conversations / messages / agent_steps / few_shots          │
│  user_preferences / user_algorithm_history / user_memories / feedback│
│  + pgvector 存 embedding                                              │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Manim 渲染 (subprocess + 60s timeout)                                 │
│  产物落 /media/* → FastAPI StaticFiles 暴露                          │
└──────────────────────────────────────────────────────────────────────┘
```

**关键点**
- **单向依赖**：Web → Agent → DAO；DAO 不知道上层存在
- **入口分诊**：复杂 prompt 走 Script Designer 出脚本 → 用户确认 → confirm 续跑 Coder；简单 prompt 直接 Coder
- **Reviewer 反馈环**：reviewer 不通过 → 写 `previous_feedback` → coder 续跑，最多 N 轮
- **统一持久化**：路由层不写埋点，全在 `AgentPersistenceMiddleware.before_agent / after_agent`
- **LLM 厂商中立**：业务只见 `ChatOpenAI`；`app/llm/client.py` 唯一出现 `ChatLiteLLM`
- **状态机**：`g.draw_mermaid()` 一行出可视化

## 🛠 本地开发

依赖：Postgres + Redis（Docker Compose，Redis 当前未接业务）、Python 3.14（conda `my-manim-environment`）、Node 20+、ManimCE + LaTeX（macOS 装 MacTex）。

```bash
# 1. 起基础设施
cd docker && docker compose up -d

# 2. 后端
conda activate my-manim-environment
cd backend
alembic upgrade head
uvicorn app.main:app --reload

# 3. 前端
cd frontend
npm install
npm run dev

# 4. 测试 & 类型检查
cd backend && python -m pytest -q          # 186 passed
cd frontend && ./node_modules/.bin/tsc --noEmit
```

启动后访问：
- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000/docs`

## 📚 文档

- [AGENTS.md](AGENTS.md) — **必读**协作指引（命令分工 / 编码规范 / 已知坑）
- [docs/product.md](docs/product.md) — 产品定位、目标用户
- [docs/architecture.md](docs/architecture.md) — 系统架构、ADR、模块结构
- [docs/workflow-design.md](docs/workflow-design.md) — Supervisor 工作流、节点职责、长期记忆
- [docs/llm-prompt.md](docs/llm-prompt.md) — Prompt 设计、few-shot 召回、Script Designer 提示词
- [docs/mvp-scope.md](docs/mvp-scope.md) — 范围、关键文件清单、Agent 表格
- [docs/tech-stack.md](docs/tech-stack.md) — 技术清单与学习地图
- [docs/coding-guidelines.md](docs/coding-guidelines.md) — 编码规范
- [docs/session-summary.md](docs/session-summary.md) — 最近改动日志（24 节）

## 🧪 v1.0 当前完成度

| 维度 | 状态 |
|---|---|
| 单算法生成（冒泡 / 二分 / BFS / 任意 prompt）| ✅ |
| 复杂 prompt 脚本确认流程 | ✅ |
| 多轮对话（refine）| ✅ |
| 长期记忆（偏好 / 算法历史 / 语义记忆）| ✅ |
| Few-shot 检索（用户自积累）| ✅ |
| Reviewer 自检 + 反馈环 | ✅ |
| 节点级 trace（agent_steps 表）| ✅ |
| 186 单元测试（含 4 个静态扫描回归保护）| ✅ |
| Worker 异步化（rq.enqueue）| ❌ v1.x TODO |
| 主动种子 few-shot（10 个高质量）| ❌ v1.x TODO |
| Docker 沙箱隔离 | ❌ v0.2 TODO |
