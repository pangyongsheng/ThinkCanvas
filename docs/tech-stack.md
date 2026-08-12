# 06 · 技术清单与学习地图

> 盘点本项目涉及的技术点，**不做实现设计**。反映 v1.0 **当前**实际状态（2026-08 P3 更新）。
>
> 跟之前版本差异：v1.0 早期 LangGraph 标"⏸️ 暂缓" — 现在 StateGraph Supervisor + Reviewer + Script Designer **已全部上线**；长期记忆 / Memory Curator / AgentMiddleware / 持久化中间件也是 v1.x 新加的。

## 🎯 定位

让 ThinkCanvas 成为 **agent 开发学习的实战场**——
每个产品模块都对应一个或多个 agent 技术点，避免"为学而学"。

## 🧱 技术清单

### 🧠 Agent 核心

| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **LangGraph `StateGraph` Supervisor** | `app/agents/supervisor.py::build_supervisor` | 节点 / 条件边 / 状态合并 / 可视化 | ✅ v1.x P2/P3 — 入口分诊 + Script Designer + Coder ↔ Reviewer |
| **LangChain 1.x `create_agent`** | `app/agents/builder.py` + `langchain.agents.create_agent` | `model=` + `tools=` + `system_prompt=` + `response_format=` | ✅ Coder 内部仍在用 |
| **LangChain `AgentMiddleware`** | `app/agents/middleware/persistence.py` | `before_agent` / `after_agent` 钩子 | ✅ v1.x 新加 — 统一持久化入口 |
| **Structured Output** | `app/agents/schemas.py`（`CodeOutput` / `CodeReview` / `SceneScript`）| JSON Schema / Pydantic / `with_structured_output` | ✅ |
| **Tool Use / Function Calling** | `app/agents/tools.py`（`@tool` validate_manim_code / render_manim_dryrun）| function schema / tool 调度 | ✅ |
| **4 层兜底**（thinking / 字符串扫描 / 代码栅栏 + 1-shot retry）| `app/agents/agent_recovery.py::invoke_with_recovery` | error recovery / meta-prompt | ✅ |
| **条件边 + 节点** | `app/agents/supervisor.py`（`_route_after_reviewer` 等）| router 设计 / string-only 硬性规则 | ✅ |
| **Self-Reflection** | Supervisor Reviewer 节点 + `previous_feedback` 续跑 | 反馈循环 / 改进 prompt | ✅ |

### 🧩 记忆与检索

| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **长期记忆** | `app/agents/memory.py` + `user_preferences` / `user_algorithm_history` / `user_memories` 表 | 记忆 schema / 召回 / 重要性评分 | ✅ v1.x P3 — `build_memory_block` 拼到 system prompt 头部 |
| **Memory Curator** | `app/agents/memory_curator.py::MemoryCurator` | LLM 提取语义记忆 / 异步分析 / 跨会话学习 | ✅ v1.x P3 |
| **RAG** | `app/agents/retriever.py::retrieve_similar_summaries` + `few_shots` 表 | chunking / embedding / 相似度 / recency fallback | ✅ v1.x — 用户自积累 |
| **Embedding + 向量库** | `app/embeddings.py`（BGE-small-zh, dim=512）+ pgvector | SentenceTransformer / pgvector 索引 / 异步 batch | ✅ |

### 🔌 接口与生态

| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **SSE 实时进度** | `app/api/v1/conversations.py::create_conversation` + `EventSource` | 单向流 / 断线重连 | ✅ 替代原计划 WebSocket |
| **MCP（Model Context Protocol）** | — | server 实现 / schema 定义 | ⏸️ v2.x 计划 |
| **多模态 Vision** | — | vision model 调用 / 视觉 prompt | ⏸️ v2.x 计划 |

### 🛡 执行环境

| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **渲染沙箱** | `app/renderers/manim.py::render_code` | subprocess + timeout + 资源保护 | ✅ 60s timeout，AST 黑名单；Docker 隔离 v0.2 TODO |

### 📈 可观测

| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **节点级 trace** | `agent_steps` 表 + `AgentPersistenceMiddleware.after_agent` | trace / steps / 工具调用记录 | ✅ v1.x 新加 |
| **LangSmith / LangFuse** | — | trace 上报 / 调试 | ❌ 不计划（内部可观测已够） |

### ⚙️ 辅助

| 技术点 | 用途 | 状态 |
|---|---|---|
| **Streaming** | 长生成 UX 不卡死（SSE） | ✅ |
| **Token / 上下文窗口管理** | few-shot top-2 / 历史 user 指令 cap 6 / 长期记忆 top-10 | ✅ |
| **分层架构** | Web → Agent → DAO 单向依赖（[architecture.md §硬性规范](architecture.md)）| ✅ v1.x 强化 |

### 📦 基础设施

| 技术点 | 用途 | 当前状态 |
|---|---|---|
| **LLM**（MiniMax-M3 / DeepSeek-V3 备胎）| 代码生成 | ✅ 默认 MiniMax-M3，OpenAI 兼容 API + LiteLLM 适配 |
| **ManimCE** | 动画渲染 | ✅ |
| **FastAPI + Pydantic** | 后端框架 | ✅ |
| **Next.js 15 + TS** | 前端 | ✅ |
| **langchain-openai + langchain-litellm + langgraph** | LLM 编排 | ✅ |
| **Postgres + SQLAlchemy + Alembic + pgvector** | 数据 | ✅ 已接业务（10+ 表）|
| **Redis + RQ** | 任务队列 | ⚠️ docker 起了，**未接业务**（v1.x 异步化 TODO）|
| **SSE（EventSource）** | 实时进度推送 | ✅ 替代原计划 WebSocket |

## 🔗 相关文档

- 系统架构 → [docs/architecture.md](architecture.md)
- 工作流与 Agent 设计 → [docs/workflow-design.md](workflow-design.md)
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 范围与里程碑 → [docs/mvp-scope.md](mvp-scope.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
