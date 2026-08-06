# Quickstart

> 本地跑通最小可跑链路的命令速查。
> 当前状态：v1.0 前 4 步已完成；Worker 异步化待落地。

---

## 0. 前置依赖

- **conda**（环境名 `my-manim-environment`）
- **Node.js 18+ / npm**
- **Docker Desktop**（跑 Postgres + Redis）

---

## 1. 一次性初始化（已跑过可跳过）

### 1.1 启动基础设施

```bash
cd docker
docker compose up -d
cd ..
```

会起：
- **Postgres** — `localhost:5432`（用户 `thinkcanvas` / 库 `thinkcanvas`）
- **Redis** — `localhost:6379`（当前未接业务，但起一下省事）

检查是否起来了：

```bash
docker ps
```

### 1.2 配置 `.env`

```bash
cp .env.example .env
# 编辑项目根 .env，把 OPENAI_API_KEY / LLM_API_KEY 填成你自己的 MiniMax key
```

> 项目根 `.env` 是单一信源（gitignored），`backend/app/config.py` 自动从项目根读。
> 必填字段：`LLM_API_KEY`（或旧字段 `OPENAI_API_KEY`，看 config 当前用的是哪个）。

### 1.3 安装后端依赖 + 数据库迁移

```bash
conda activate my-manim-environment
cd backend
pip install -e ".[dev]"
alembic upgrade head
cd ..
```

### 1.4 安装前端依赖（如未装）

```bash
cd frontend
npm install
cd ..
```

---

## 2. 启动开发服务（需要 3 个终端）

> 每个终端独立：`conda activate my-manim-environment`

| 终端 | 命令 | 端口 | 作用 |
|---|---|---|---|
| **后端 API** | `cd backend && uvicorn app.main:app --reload --port 8000` | 8000 | FastAPI + 同步渲染 |
| **前端** | `cd frontend && npm run dev` | 3000 | Next.js 15 |
| ~~RQ Worker~~ | — | — | ⚠️ **尚未实现** |

**终端 1 — 后端：**

```bash
conda activate my-manim-environment
cd backend
uvicorn app.main:app --reload --port 8000
```

**终端 2 — 前端：**

```bash
conda activate my-manim-environment
cd frontend
npm run dev
```

启动后访问：

- 前端页面：http://localhost:3000
- API 文档：http://localhost:8000/docs
- 视频静态目录：http://localhost:8000/media/<task_id>.mp4

---

## 3. 仅跑 Manim 渲染验证（不需要后端）

```bash
./verify.sh
```

输出视频：`media/videos/01_hello/480p15/HelloThinkCanvas.mp4`

---

## 4. 当前架构（同步渲染）

```
浏览器 → POST /api/v1/render
       → API 进程内同步跑 CoderAgent.run_streaming + Manim subprocess
       → 返回 {video_url: /media/<task_id>.mp4}
```

⚠️ 渲染期间 API 阻塞（60s 超时上限）。简单但有缺陷。

---

## 5. TODO：拆成异步队列（Worker）

| 进程 | 职责 |
|---|---|
| uvicorn (FastAPI) | 接收请求 → 写任务到 Redis → 立即返回 `task_id` |
| Redis | 任务队列 |
| RQ Worker | 从 Redis 拉任务 → 跑 Manim 渲染 → 写结果回 DB |
| 前端 (Next.js) | 调用 API → 轮询任务状态 → 展示视频 |

落地清单：
- [ ] `backend/app/workers/` 写渲染任务函数
- [ ] `api/v1/render.py` 改用 `rq.enqueue(...)`
- [ ] 新增 `GET /api/v1/tasks/{id}` 查状态

---

## 6. 常见问题

### `connection refused: postgres` / `redis`
→ docker 没起：`cd docker && docker compose up -d`

### `OPENAI_API_KEY not set` / LLM 报 401
→ 项目根 `.env` 没配 key 或没 cp `.env.example .env`

### `alembic` 找不到数据库
→ 同上 Postgres 没起；或 `alembic upgrade head` 跑的位置不对（要在 `backend/` 下）

### 前端 3000 调不到后端 8000
→ 看 `backend/.env` 里的 `CORS_ORIGINS=http://localhost:3000`；前端 `.env.local` 里 API base URL 指向 8000

### LaTeX 报错 `MathTex not found`
→ 预期内：当前环境没装 LaTeX，prompt 已禁用 `MathTex`，用 `Text()` 代替
