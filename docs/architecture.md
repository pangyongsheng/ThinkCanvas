# 02 · 系统架构

> 反映 v1.0 实际状态。所有路径、组件、命令以仓库代码为准。

## 🏗 整体架构（v1.0 现状）

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│  Browser │───▶│  Next.js │───▶│  FastAPI │
│  (用户)  │◀───│  Web UI  │◀───│  Backend │◀──▶ Postgres
└──────────┘    └──────────┘    └────┬─────┘
      ▲               ▲               │
      │               │               │ SSE（实时进度）
      │               └───────────────┘
      │                                │
      │            渲染完返回视频 URL   ▼
      └────────── 静态文件 ◀──── /media/* (FastAPI StaticFiles)
                                   │
                                   ▼
                            ┌──────────┐
                            │  Manim   │
                            │ Renderer │ (subprocess，in-process)
                            └──────────┘
```

**关键变化（vs 原规划）**：
- ❌ ~~Redis + RQ Worker 异步队列~~ — **未实现**；当前所有渲染在 API 进程内同步执行
- ❌ ~~WebSocket 推送进度~~ — **改用 SSE**（`GET /api/v1/generate/stream`）
- ✅ MiniMax-M3 作为默认 LLM（不是 DeepSeek）
- ✅ LangChain 零件（parser / LCEL） + 手写 agent loop（不是 LangGraph 状态机）

## 🔄 数据流（端到端）

```
[1] 用户输入 "冒泡排序"
   ↓
[2] 前端 POST /api/v1/render { prompt, quality }
   │
   ▼
[3] FastAPI 同步执行
   ├─ CoderAgent.run_streaming(prompt)
   │   ├─ LLM 生成代码（MiniMax-M3，结构化 JSON 输出）
   │   ├─ validate_only_retry（最多 N 次）
   │   ├─ SSE 推送 {"stage": "coding", "attempt": 1}
   │   └─ SSE 推送 {"stage": "validated"}
   ├─ 写代码到 tmp/{task_id}.py
   ├─ subprocess.run(['manim', ...], timeout=60)
   ├─ 读产物 video.mp4 → 落 media/{task_id}.mp4
   └─ SSE 推送 {"stage": "done", "video_url": "/media/{task_id}.mp4"}
   ↓
[4] 前端 EventSource 收到 done → 渲染 <video>
```

**注意**：API 在渲染期间会**阻塞**当前请求（60s 超时上限）。这是已知简化，未来拆 Worker。

## 💻 技术栈

### 前端
| 技术 | 版本 | 状态 |
|---|---|---|
| **Next.js** | 15（App Router） | ✅ |
| TypeScript | 5+ | ✅ |
| Tailwind CSS | 3+ | ✅ |
| **SSE 订阅**（`EventSource`） | — | ✅ 替代原计划的 WebSocket |

### 后端
| 技术 | 版本 | 状态 |
|---|---|---|
| **Python** | 3.14（conda 环境 `my-manim-environment`） | ✅ |
| **FastAPI** | latest | ✅ |
| uvicorn | latest | ✅ |
| Pydantic | 2+ | ✅ |
| SQLAlchemy + Alembic | 2+ | ⚠️ 库在，业务未启用 |
| **langchain-openai** | latest | ✅（接 MiniMax OpenAI 兼容 API） |

### LLM
| 角色 | 模型 | 提供方 | 状态 |
|---|---|---|---|
| **默认** | **MiniMax-M3** | MiniMax（OpenAI 兼容 API） | ✅ |
| 备胎 | DeepSeek-V3 / Qwen2.5-Coder | — | 🔜 留切换位 |

> **MiniMax 不支持 `tool_calls`**，因此不能直接用 LangChain 的 `bind_tools` / `create_agent` / LangGraph `create_react_agent`。当前实现是**手写 agent loop + LangChain 零件**（parser / LCEL）。
> 详见 [docs/session-summary.md](session-summary.md)。

### 渲染
| 技术 | 用途 | 状态 |
|---|---|---|
| **ManimCE** | 动画引擎 | ✅ |
| **subprocess** | 沙箱 | ✅（v0.2 计划升级 Docker） |
| ffmpeg | 视频编码 | ✅ |
| 60s timeout | 资源保护 | ✅ |

### 基础设施
| 组件 | 状态 |
|---|---|
| Docker (Postgres + Redis) | ✅ 起了，**Redis 未接业务** |
| 本地文件存储 `./media/` | ✅，通过 `/media` 静态挂载 |
| 阿里云 OSS / S3 | ❌ 未做 |

## 🧱 实际模块结构（与代码一致）

```
backend/
├── app/
│   ├── main.py                       # FastAPI 入口
│   ├── config.py                     # 读项目根 .env；model_name="MiniMax-M3"
│   ├── agents/
│   │   ├── react_coder.py            # ⚠️ 死代码：LangGraph ReAct（MiniMax 不支持 tool_calls）
│   │   ├── tools.py                  # ⚠️ 死代码：@tool 装饰的 validate_manim_code / render_manim_dryrun
│   │   └── coder/                    # ✅ 实际使用的 agent
│   │       ├── __init__.py
│   │       ├── parser.py             # CodeOutput + parse_with_fallback + strip_think_blocks
│   │       ├── chain.py              # PROMPT_TEMPLATE + build_chain (RunnableSequence)
│   │       ├── retry.py              # load_system_prompt + build_user_message + validate_only_retry
│   │       ├── coder.py              # CoderAgent 类 + AgentStep + AgentResult
│   │       ├── sync.py               # run_sync + GenerateOutcome
│   │       └── stream.py             # run_streaming（SSE 流式）
│   ├── api/v1/
│   │   ├── generate.py               # POST /generate (legacy), GET /generate/stream (生产用), POST /generate/agent (死)
│   │   ├── render.py                 # POST /render
│   │   ├── health.py                 # GET /health
│   │   └── readyz.py                 # GET /readyz
│   ├── renderers/
│   │   └── manim.py                  # subprocess + 60s 超时
│   ├── tools/validator.py            # AST + 危险模式 + Scene 子类检查
│   ├── llm/client.py                 # ChatOpenAI 配 MiniMax base_url
│   └── core/
│       └── ...                       # 预留扩展
├── tests/agents/
│   └── test_coder.py                 # 4/4 测试通过
├── pyproject.toml
└── .env.example

shared/prompts/
├── system/v1.txt                     # System prompt（含硬性约束）
└── examples/                         # ⚠️ 当前为空目录；v1 只剩"冒泡排序"在 system prompt 里

frontend/
├── app/page.tsx                      # EventSource 订阅 + 进度条 + 视频 + 代码框
└── lib/api.ts                        # generateCode / renderManim / subscribeGenerate

docker/docker-compose.yml             # postgres + redis（redis 未接业务）
```

## 📝 关键决策记录 (ADR)

### ADR-001 · 默认 LLM 切换为 MiniMax-M3
- **决策**：默认从 DeepSeek-V3 切到 **MiniMax-M3**
- **理由**：公司内部模型、可控；OpenAI 兼容 API
- **代价**：不支持 `tool_calls`，被迫手写 agent loop
- **缓解**：用 LangChain 的零件（parser / LCEL）但不用 agent 大脑

### ADR-002 · 同步渲染，不上 Worker（v1.0 简化）
- **决策**：渲染在 API 进程内同步执行，**不**接 Redis / RQ Worker
- **理由**：v1.0 范围是"3 个算法端到端跑通"；异步化是 v1.x 工作
- **代价**：渲染期间 API 阻塞；60s 超时上限
- **缓解**：前端用 SSE 流式推进度，UX 不完全卡死

### ADR-003 · SSE 替代 WebSocket
- **决策**：实时进度推送用 **SSE**（`EventSource`），不用 WebSocket
- **理由**：单向（服务端 → 客户端）、HTTP 友好、调试简单
- **未来**：需要双向交互时再换 WebSocket

### ADR-004 · ManimCE 而非 ManimGL
- 同原版，未变

### ADR-005 · LangChain 零件 + 手写 loop（不绑 LangGraph）
- **决策**：用 `langchain-openai` 的 ChatOpenAI、`PydanticOutputParser`、`StrOutputParser`、`RunnableSequence`，但 agent 大脑**手写**
- **理由**：MiniMax 不支持 tool_calls；LangGraph ReAct 跑不通
- **迁移路径**：未来若换支持 tool_calls 的 LLM（如 GPT-4o），可平滑迁移到 `langgraph.StateGraph`

## 🚨 安全考虑

| 风险 | 缓解 | 状态 |
|---|---|---|
| 死循环 | subprocess timeout=60s | ✅ |
| 删文件 / 网络请求 | AST 黑名单模式（`open` / `os.` / `requests` 等） | ✅ |
| 内存炸弹 | ulimit（**待加**） | ❌ |
| Docker 隔离 | v0.2 引入 | ❌ |

## 📈 性能预算（实测参考）

| 阶段 | 耗时预算 | 实测 |
|---|---|---|
| LLM 推理 | < 20s | — |
| Manim 渲染 | < 30s | — |
| **总** | **< 60s**（subprocess 超时上限） | — |

> 实测数据需 Step 6（3 算法 × 10 次）跑完才有。

## 🔮 TODO / 未来扩展

| 项 | 说明 | 优先级 |
|---|---|---|
| **Worker 异步化** | `backend/app/workers/` 写渲染任务 + `rq.enqueue` 改 API | 高（解决 API 阻塞） |
| **持久化** | Step 5 — user / history 表 + alembic 迁移 + 中英切换 | 高 |
| **few-shot 库** | v1.0 要求 3 个算法，目前 system prompt 里只塞了冒泡排序 | 高 |
| **Docker 沙箱** | v0.2 计划 | 中 |
| **LangGraph 状态机** | 当前手写 loop，未来用 `langgraph.StateGraph` 重构 agent | 中 |
| **LangSmith / LangFuse** | 可观测 | 中 |
| **OSS / S3** | 视频存储 | 低 |
| **多 LLM 切换** | DeepSeek-V3 / Qwen2.5-Coder 备胎 | 低 |

## 🔗 相关文档

- 范围与里程碑 → [docs/mvp-scope.md](mvp-scope.md)
- 工作流与 Agent 设计 → [docs/workflow-design.md](workflow-design.md)（与现状有出入，注意甄别）
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 启动命令 → [docs/quickstart.md](quickstart.md)
