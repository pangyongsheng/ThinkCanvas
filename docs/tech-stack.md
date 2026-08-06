# 06 · 技术清单与学习地图

> 盘点本项目涉及的技术点，**不做实现设计**。
> 只标范围 + 学习目标；实现细节等开发阶段在模块代码里展开。

## 🎯 定位

让 ThinkCanvas 成为 **agent 开发学习的实战场**——
每个产品模块都对应一个或多个 agent 技术点，避免"为学而学"。

## 🧱 技术清单

### 🧠 Agent 核心
| 技术点 | 项目里的落点 | 学习目标 | 状态 |
|---|---|---|---|
| **LangGraph** | 计划用 pipeline 状态机（planning / coding / validating / fixing / rendering） | 状态机、conditional edge、checkpointer、可视化 | ⏸️ 暂缓 — MiniMax 不支持 tool_calls，`react_coder.py` 是死代码 |
| **标准 `create_agent` + LiteLLM 适配层**（2026-08 升级）| `app/agents/builder.py` + `app/llm/client.py` | `langchain.agents.create_agent` + `response_format=CodeOutput` + `langchain-litellm` | ✅ 实际在用 |
| **Structured Output** | LLM 输出 `{thought, code}` → Pydantic 解析 | JSON Schema、Pydantic、OutputParser | ✅ |
| **Tool Use / Function Calling** | — | function schema、tool 调度 | ⏸️ 等支持 tool_calls 的 LLM |
| **ReAct** | — | Thought / Action / Observation | ⏸️ 同上 |
| **Self-Reflection** | 错误重试时把 stderr 回喂 LLM | meta-prompt | ✅ |

### 🧩 记忆与检索
| 技术点 | 项目里的落点 | 学习目标 |
|---|---|---|
| **持久化记忆** | user + 历史表 + 跨 session 召回偏好 / 过去算法 | 记忆 schema、retrieval 流程 |
| **RAG** | 选 few-shot：按 prompt 相似度挑 1-2 个塞 prompt | chunking、embedding、相似度 |
| **Embedding + 向量库** | RAG 底层 | pgvector / Chroma |

### 🔌 接口与生态
| 技术点 | 项目里的落点 | 学习目标 |
|---|---|---|
| **MCP（Model Context Protocol）** | 把 validator / renderer / history 暴露成 MCP server | server 实现、schema 定义、跨 client 调用 |
| **多模态 Vision** | 截图输入 | vision model 调用、视觉 prompt 设计 |

### 🛡 执行环境
| 技术点 | 项目里的落点 | 学习目标 |
|---|---|---|
| **渲染沙箱** | LLM 写出的代码隔离执行 | subprocess ulimit → Docker（v0.2 升级） |

### 📈 可观测
| 技术点 | 项目里的落点 | 学习目标 |
|---|---|---|
| **Observability** | 调 prompt / debug agent 行为 | trace、metrics、LangSmith / LangFuse 接入 |

### ⚙️ 辅助
| 技术点 | 用途 |
|---|---|
| **Streaming** | 长生成 UX 不卡死 |
| **Prompt Caching** | 节省 token 费用 |
| **Token / 上下文窗口管理** | 限长 prompt、few-shot 截断 |

### 📦 基础设施（详见 [architecture.md](architecture.md)）
| 技术点 | 用途 | 当前状态 |
|---|---|---|
| LLM（**MiniMax-M3** / DeepSeek-V3 备胎） | 代码生成 | ✅ 默认 MiniMax-M3，OpenAI 兼容 API |
| ManimCE | 动画渲染 | ✅ |
| FastAPI + Pydantic | 后端框架 | ✅ |
| Next.js + TS | 前端 | ✅ |
| langchain-openai + LCEL | LLM 调用骨架 | ✅ |
| Redis + RQ | 任务队列 | ⚠️ docker 起了，**未接业务** |
| Postgres + SQLAlchemy + Alembic | 数据 | ⚠️ 库在，无业务表 |
| SSE（EventSource） | 实时进度推送 | ✅（替代原计划 WebSocket） |


