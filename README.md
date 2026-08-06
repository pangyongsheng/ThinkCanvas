# ThinkCanvas

> **AI 驱动的算法/数学动画生成器**
> 输入文字描述，自动生成 3Blue1Brown 风格的 Manim 视频。

![status](https://img.shields.io/badge/status-MVP%20v1.0-yellow)
![python](https://img.shields.io/badge/python-3.14-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## 🎯 一句话
让不会 Manim 的人，也能产出专业的算法/数学可视化视频。

## 📚 文档目录

| 文档 | 内容 |
|---|---|
| [docs/product.md](docs/product.md) | 产品定位、目标用户、价值主张 |
| [docs/mvp-scope.md](docs/mvp-scope.md) | v1.0 范围、6 步开发步骤、关键文件清单 |
| [docs/architecture.md](docs/architecture.md) | 系统架构、技术选型、数据流 |
| [docs/tech-stack.md](docs/tech-stack.md) | 技术清单与学习地图 |
| [docs/llm-prompt.md](docs/llm-prompt.md) | LLM Prompt 设计、Few-shot、重试策略 |
| [docs/workflow-design.md](docs/workflow-design.md) | ⭐ Agent 设计、工作流、扩展点 |
| [docs/session-summary.md](docs/session-summary.md) | 最近 session 的改动总结 |

## 🛠 当前进度（v1.0 → v1.1）

- [x] 命名：ThinkCanvas
- [x] 环境验证：Manim 渲染管线 OK
- [x] 产品/架构文档完成（7 份）
- [x] 本地基础设施：Postgres + Redis（Docker，Redis 未接业务）
- [x] **基建联通**：Next 15 + FastAPI + 后端最小 hello + 接 Postgres
- [x] **LLM 适配层**：LiteLLM 抹平 MiniMax 协议差异，业务层用 LangChain 标准 `ChatOpenAI` + `create_agent` 全套
- [x] **Code 流水线**：标准 LangChain 1.x `create_agent(model=, tools=, system_prompt=, response_format=)`；手写 agent loop 全部删除（9 个文件 → 4 个核心）
- [x] **渲染流水线**：subprocess + 60s timeout；产物落 `./media/`；`/media` 静态文件挂载
- [x] **Web UI 最小版**：输入 / Generate / 进度条（SSE）/ 视频 / 代码框 / 重渲染
- [x] **可观测性**：stdlib logging + structlog + FastAPI 全局异常中间件；`run_agent` 每次进出都打日志
- [x] **多轮对话**：Conversations + Messages 双表 + refine agent；UI 收敛到右侧对话面板；prompt 喂"最近 6 条用户原话 + 上一版代码 + 本次指令"
- [x] **Studio UI**：3 栏布局（可折叠历史 + 视频/代码主区 + 对话面板），代码默认折叠
- [x] **用户系统（匿名 ULID）**：`users` 表 + `X-User-Id` header 中间件 + 前端 localStorage 持久化；历史数据迁移到匿名用户
- [ ] **持久化记忆**：user_preferences + user_algorithm_history；按偏好 / 过去算法塞 prompt
- [ ] **few-shot 检索**：把硬编码 few-shot 抽到 `few_shots` 表，按 prompt 关键词选 1-2 个拼进 system prompt
- [ ] **Worker 异步化**：解 API 阻塞（v1.x）
- [ ] **端到端验证**：3 算法 × 10 次成功率 / 时长（Step 6）

## 🏗 架构一句话

```
.env → app.config → app.llm.client (ChatLiteLLM 封装为 ChatOpenAI)
                              ↓
        app.agents.builder (create_agent 工厂，response_format=CodeOutput)
                              ↓
        ┌─────────────────────────┬─────────────────────────────┐
        │  app.agents.react_coder │ 单次生成 wrapper（薄壳）       │
        │  app.agents.refine      │ 多轮调整（拼 user history）    │
        │  两个 wrapper 都通过     │ build_agent(...) 同一家工厂      │
        └─────────────────────────┴─────────────────────────────┘
                              ↓
        ┌─────────────────────────┬─────────────────────────────┐
        │  app.api.v1.generate    │ POST /generate, /generate/stream │
        │  app.api.v1.conversations│ /conversations, /refine SSE │
        └─────────────────────────┴─────────────────────────────┘
                              ↓
        X-User-Id 中间件 → db.models.{User, Conversation, Message}
                              ↓
        前端: page.tsx + HistorySidebar + ConversationPanel + CodeViewer
        + lib/user.ts（ULID）+ lib/api.ts（fetchJson 加 X-User-Id）
```

LiteLLM 在 `client.py` 内是唯一出现的地方，业务层只见 `ChatOpenAI`。
两层 wrapper（`run_agent` / `run_refine`）共享同一个 `build_agent` 工厂，按
`(style_id, extra_system_prompt)` 维度 lru_cache。

## 🧪 快速验证

只验证 Manim 渲染：

```bash
./verify.sh
# 跑 demos/01_hello.py，输出 mp4
```

启动后端开发服务（详见 [docs/quickstart.md](docs/quickstart.md)）：

```bash
conda activate my-manim-environment
cd backend
uvicorn app.main:app --reload --port 8000
```

跑测试：

```bash
cd backend
python -m pytest tests/agents/test_coder.py -v
# 6/6 通过
```

## 🤝 贡献

个人项目阶段，欢迎提 Issue。
