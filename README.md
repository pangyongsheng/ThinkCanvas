# ThinkCanvas

> 输入文字，自动生成 3Blue1Brown 风格的 Manim 算法/数学动画视频。

让不会 Manim 的人，也能产出专业的算法可视化视频。

![status](https://img.shields.io/badge/status-active-success)
![python](https://img.shields.io/badge/python-3.14-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## ✨ 功能

| | |
|---|---|
| 🎬 **视频生成** | 文字 prompt → 完整 Manim 视频，720p / 60s timeout |
| 🔁 **多轮调整** | 右侧对话面板说"换成红底"，自动重写代码 + 重渲染 |
| 👤 **个人身份** | 历史和偏好自动保留 |
| 📚 **Few-shot 库** | 点"👍 收藏为范例"积累好例子，自动存 embedding |
| 🔍 **Few-shot 检索** | 按 prompt 相似度召回 top-k |
| 🧠 **持久化记忆** | 按偏好 / 过去算法塞 prompt |
| 🤖 **标准 Agent 范式** | 业务层用 LangChain 1.x  |
| 🔌 **LLM 可插拔** | LiteLLM 把多厂商协议归一化，换厂商改一行 |
| 🛡 **多层兜底** | 4 道防线自动救回 |
| 🏷 **结构化输出** | Pydantic `CodeOutput{thought, code}` 约束，自动校验 |

## 🏗 架构

```
.env → app.config → app.llm.client (ChatLiteLLM → ChatOpenAI)
                              ↓
        app.agents.builder (create_agent 工厂 + lru_cache)
                              ↓
        ┌─────────────────────┬───────────────────────┐
        │  run_agent          │ run_refine            │
        │  单次生成            │ 多轮调整 + 历史召回     │
        │  两个 wrapper 都走 build_agent(extra_prompt=...) │
        └─────────────────────┴───────────────────────┘
                              ↓
        ┌─────────────────────┬───────────────────────┐
        │  /generate/stream   │ /conversations + /refine SSE │
        │  /few_shots         │ X-User-Id 中间件            │
        └─────────────────────┴───────────────────────┘
                              ↓
        Postgres：users / conversations / messages / few_shots
                              ↓
        前端：3 栏布局（左历史 / 中视频+代码 / 右对话面板）
```

**关键点**
- LLM 一律走标准 LangChain 1.x `create_agent`；LiteLLM 适配藏在 `app/llm/client.py`，换厂商只改一处
- `run_agent` / `run_refine` 共享 `build_agent` 工厂，按 `(style_id, extra_prompt)` 缓存
- 删除会话自动连带删生成的 mp4 文件

## 🛠 本地开发

依赖：Postgres + Redis（Docker Compose）、Python 3.14（conda `my-manim-environment`）、Node 20+、ManimCE + LaTeX（macOS 装 MacTex）。

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
cd backend && python -m pytest -q    # 107 passed
cd frontend && ./node_modules/.bin/tsc --noEmit
```

启动后访问：
- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000/docs`

## 📚 文档

- [docs/product.md](docs/product.md) — 产品定位、目标用户
- [docs/architecture.md](docs/architecture.md) — 模块结构、ADR
- [docs/llm-prompt.md](docs/llm-prompt.md) — Prompt 设计、few-shot、兜底策略
- [docs/mvp-scope.md](docs/mvp-scope.md) — 范围、关键文件清单
- [docs/session-summary.md](docs/session-summary.md) — 最近改动日志
- [AGENTS.md](AGENTS.md) — 协作指引（必读）
