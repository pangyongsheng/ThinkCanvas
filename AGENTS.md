# AGENTS.md

> 接手必读。5 分钟看完就能动手。

## 项目

**ThinkCanvas**：文字描述 → LLM 生成 Manim 代码 → 渲染成算法/数学动画视频。

## 必读文档

1. [docs/coding-guidelines.md](docs/coding-guidelines.md) — 编码规范（**先看**）
2. [docs/architecture.md](docs/architecture.md) — 模块结构 + ADR
3. [docs/llm-prompt.md](docs/llm-prompt.md) — Prompt / few-shot / 兜底策略
4. [docs/session-summary.md](docs/session-summary.md) — 最近改动日志

## 硬性约束

- **LLM**：`MiniMax-M3` via LiteLLM；不要换厂商
- **样式**：3b1b / minimal / academic，新加走 `shared/prompts/styles/*.md` + `app/agents/styles.py::STYLE_IDS`
- **渲染超时**：60s（macOS 需要 `app.main._augment_path_with_tex_bin` 拼 `/Library/TeX/texbin` 到 PATH）
- **academic 风格背景色**：Scene 构造里 `self.camera.background_color = "#FFFFFF"`；`config.background_color` 渲染期太晚

## 用户偏好

- 沟通：**极简**。"说人话"、"别长篇大论"
- 代码：单文件 ≤ 300 行（公开模块 ≤ 400），超了拆 helper
- docstring：**中文**
- 不到 5 行别开新文件

## 命令速查

```bash
# 后端
cd backend && uvicorn app.main:app --reload

# 前端
cd frontend && npm run dev

# 测试
cd backend && python -m pytest -q    # 107 passed

# 类型检查
cd frontend && ./node_modules/.bin/tsc --noEmit

# 迁移
cd backend && alembic upgrade head
```

## 已知坑

- **MiniMax `result.content` 是 typed-block list**，不是 str。任何 `.strip()` / `.split()` 直接调用都会崩。处理见 `app/agents/summarizer.py::_extract_text_from_message`——单次 LLM 调用（非 agent loop）也要走这个 helper。
- **MiniMax 偶发只输出 `[thinking]` 块** → `app/agents/agent_recovery.py` 四层兜底
- **M3 thinking 占满预算** → 1-shot retry
- **测试无 `aiosqlite`** → 用同步 in-memory SQLite，不上 async session fixture
