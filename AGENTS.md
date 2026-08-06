# AGENTS.md · Codex 协作指引

> 这个文件给 Codex / 其他 AI 协作者快速 onboarding。先读它，再去翻 `docs/` 详细资料。

## 项目一句话

**ThinkCanvas**：文字描述 → LLM 生成 Manim 代码 → 渲染成算法/数学动画视频。

## 必读文档（按顺序）

1. `docs/coding-guidelines.md` — 编码规范（**先看这个**，文件行数 / docstring 风格都在这）
2. `docs/architecture.md` — 模块结构 + 7 条 ADR
3. `docs/mvp-scope.md` — v1.0 / v1.1 范围 + 下一步建议
4. `docs/llm-prompt.md` — Prompt 设计 / few-shot / 兜底策略
5. `docs/session-summary.md` — 最近 session 的改动日志

## 硬性约束（不能改）

- **LLM**：`MiniMax-M3` via LiteLLM（OpenAI 兼容 API），不要换厂商
- **样式**：3b1b / minimal / academic 三个，新加走 `shared/prompts/styles/*.md` + `app/agents/styles.py::STYLE_IDS`
- **渲染超时**：60s（macOS 上需要 augment PATH 拼 `/Library/TeX/texbin`，已在 `app.main._augment_path_with_tex_bin`）
- **academic 风格背景色**：必须在 Scene 构造里 `self.camera.background_color = "#FFFFFF"`，`config.background_color` 渲染期太晚
- **manim 渲染**：subprocess + 60s timeout，产物落 `backend/media/`

## 用户偏好（沟通 / 代码风格）

- 沟通：**极简**。"说人话"、"别长篇大论"
- 代码：单文件 ≤ 300 行（公开模块 ≤ 400）；超了就拆 helper
- docstring：**中文**
- 不到 5 行就别开新文件

## 启动命令

```bash
# 后端（必须在 backend/ 目录起，watchfiles 才能正确监控）
cd backend
/opt/miniconda3/envs/my-manim-environment/bin/uvicorn app.main:app --reload

# 前端
cd frontend
npm run dev

# 测试
cd backend
/opt/miniconda3/envs/my-manim-environment/bin/python -m pytest -q

# 类型检查
cd frontend
./node_modules/.bin/tsc --noEmit

# 迁移
cd backend
/opt/miniconda3/envs/my-manim-environment/bin/alembic upgrade head
```

## 当前进度（2026-08-06）

v1.0 6 步基线 + v1.1.1-1.1.3（多轮对话 / 用户系统 / 规范化）已上线。

**接下来 v1.1 的两件事**（按用户最近的决议）：
1. 持久化记忆（`user_preferences` + `user_algorithm_history`）
2. Few-shot 检索（把硬编码 few-shot 抽到 `few_shots` 表，按 prompt 关键词粗筛）

详见 `docs/mvp-scope.md` 的 v1.1 段落。

## 已知坑

- **MiniMax 偶发只输出 `[thinking]` 块** → `agent_recovery.py` 四层兜底
- **MiniMax `result.content` 是 typed-block list**（`[{"type":"thinking",...}, {"type":"text","text":"..."}]`），不是 str。任何直接对 `result.content.strip()` / `.split()` 的调用都会崩。处理方法见 `app/agents/summarizer.py::_extract_text_from_message`——单次 LLM 调用（非 agent loop）也要走这个 helper。
- **M3 thinking 占满预算** → 1-shot retry
- **No module 'aiosqlite'** → 测试用同步 in-memory SQLite，不上 async session fixture
- **Sandbox 不能 git 写** → 代码改动直接 `mv` / `sed -i`，不依赖 `git mv`
- **Sandbox 不能 pip install** → 装新依赖需用户手动跑
