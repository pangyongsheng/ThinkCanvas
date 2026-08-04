# 06 · 技术清单与学习地图

> 盘点本项目涉及的技术点，**不做实现设计**。
> 只标范围 + 学习目标；实现细节等开发阶段在模块代码里展开。

## 🎯 定位

让 ThinkCanvas 成为 **agent 开发学习的实战场**——
每个产品模块都对应一个或多个 agent 技术点，避免"为学而学"。

## 🧱 技术清单

### 🧠 Agent 核心
| 技术点 | 项目里的落点 | 学习目标 |
|---|---|---|
| **LangGraph** | pipeline 状态机（planning / coding / validating / fixing / rendering） | 状态机、conditional edge、checkpointer、可视化 |
| **ReAct** | 单 Agent 内部的"思考 + 调工具"循环 | Thought / Action / Observation 范式 |
| **Tool Use / Function Calling** | 调 validator / renderer / history-searcher | function schema 设计、tool 调度 |
| **Structured Output** | LLM 输出 plan dict / code / error | JSON Schema、Pydantic、Tool output mode |
| **Self-Reflection** | agent 自检代码（缓解"算法表达不精确"风险） | 自我评估 loop、meta-prompt |

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
| 技术点 | 用途 |
|---|---|
| LLM（**MiniMax-M3** / DeepSeek-V3 备胎） | 代码生成 |
| ManimCE | 动画渲染 |
| FastAPI + Pydantic | 后端框架 |
| Next.js + TS | 前端 |
| Redis + RQ | 任务队列 |
| Postgres + SQLAlchemy + Alembic | 数据 |
| WebSocket | 实时进度推送 |

## 🗺 学习路径

| 阶段 | 重点技术点 |
|---|---|
| **v1.0**（3 算法端到端跑通） | LangGraph · Tool Use · Structured Output · 持久化记忆 · 沙箱（subprocess）· Streaming · Observability |
| **v1.x**（扩算法 / 场景广度） | RAG / Embedding · Self-Reflection · Vision · Prompt Caching |
| **v2.0**（协作 / 多模产物） | MCP · ReAct 深化（多工具调度） |

## ❌ 本文档不做的事

- ❌ 不写具体 schema
- ❌ 不定库版本号
- ❌ 不画模块依赖图
- ❌ 不对比 LLM / 向量库的 provider 优劣

## 🔗 与其他文档的关系

- 策略 / 范围 → [product.md](product.md)
- 系统架构 → [architecture.md](architecture.md)
- 工作流与 Agent 设计 → [workflow-design.md](workflow-design.md)
- LLM Prompt → [llm-prompt.md](llm-prompt.md)
