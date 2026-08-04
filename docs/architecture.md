# 03 · 系统架构

## 🏗 整体架构

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Browser │───▶│  Next.js │───▶│  FastAPI │───▶│  Redis   │
│  (用户)  │    │  Web UI  │    │  Backend │    │  Queue   │
└────▲─────┘    └──────────┘    └────┬─────┘    └────┬─────┘
     │                               │                │
     │         WebSocket             │                │
     └───────────────────────────────┘                │
                                                     ▼
                                              ┌──────────┐
                                              │  RQ      │
                                              │  Worker  │
                                              └────┬─────┘
                                                   │
                                ┌──────────────────┼──────────────────┐
                                ▼                  ▼                  ▼
                          ┌──────────┐      ┌──────────┐      ┌──────────┐
                          │  DeepSeek│      │  Manim   │      │  Local   │
                          │  LLM API │      │ Renderer │      │  Storage │
                          └──────────┘      └──────────┘      └──────────┘
```

## 🔄 数据流（端到端）

```
[1] 用户输入
   "冒泡排序"
   ↓
[2] Web 前端
   POST /api/generate
   { prompt: "冒泡排序", quality: "720p" }
   ↓
[3] FastAPI
   ├─ 校验 prompt
   ├─ 创建 task_id (UUID)
   ├─ 入队 Redis
   └─ 返回 { task_id, status: "pending" }
   ↓
[4] 前端
   ├─ 打开 WebSocket /ws/task/{task_id}
   └─ 显示"生成中..."
   ↓
[5] RQ Worker
   ├─ 调 DeepSeek API → Manim 代码
   ├─ 校验代码
   ├─ 写入临时文件 /tmp/{task_id}.py
   ├─ subprocess.run(['manim', ...], timeout=60)
   ├─ 读取输出 /tmp/{task_id}/output.mp4
   ├─ 存到 media/{task_id}.mp4
   └─ WebSocket 推送 { status: "done", video_url: "..." }
   ↓
[6] 前端
   ├─ 收到 WebSocket 消息
   ├─ 显示视频播放器
   └─ 提供下载按钮
```

## 💻 技术栈

### 前端
| 技术 | 版本 | 选择理由 |
|---|---|---|
| **Next.js** | 14+ | App Router、SSR、API routes |
| **TypeScript** | 5+ | 类型安全 |
| **Tailwind CSS** | 3+ | 快速样式 |
| **shadcn/ui** | latest | 组件库，可定制 |
| **Zustand** | 4+ | 轻量状态管理 |

### 后端
| 技术 | 版本 | 选择理由 |
|---|---|---|
| **Python** | 3.12 | Manim 兼容性最好 |
| **FastAPI** | 0.110+ | 异步、WebSocket、自动文档 |
| **uvicorn** | latest | ASGI 服务器 |
| **Pydantic** | 2+ | 数据校验 |
| **SQLAlchemy** | 2+ | ORM（未来用） |

### 任务队列
| 技术 | 用途 |
|---|---|
| **Redis** | 队列 + 缓存 |
| **RQ (Redis Queue)** | Python 任务队列（比 Celery 轻） |

### LLM
| 优先级 | 模型 | 提供方 | 用途 |
|---|---|---|---|
| 1 (默认) | **DeepSeek-V3** | DeepSeek | 代码生成 |
| 2 (备选) | Qwen2.5-Coder-32B | 阿里 | 备胎 |
| 3 (备选) | GLM-4-Plus | 智谱 | 备胎 |

### 渲染
| 技术 | 用途 |
|---|---|
| **ManimCE** | 动画引擎 |
| **ffmpeg** | 视频编码 |
| **Docker** | 沙箱隔离（v0.2 引入） |

### 存储
| 阶段 | 方案 |
|---|---|
| 开发 | 本地文件系统 `./media/` |
| 生产 (v0.5) | 阿里云 OSS / AWS S3 |

## 🧱 模块设计

### Backend 模块
```
backend/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置（环境变量）
│   ├── api/
│   │   ├── generate.py      # POST /api/generate
│   │   ├── task.py          # GET /api/task/:id
│   │   └── ws.py            # WebSocket
│   ├── core/
│   │   ├── llm.py           # DeepSeek 客户端
│   │   ├── prompt.py        # Prompt 构造
│   │   ├── validator.py     # 代码校验
│   │   └── renderer.py      # Manim 沙箱
│   ├── workers/
│   │   └── render_worker.py # RQ 任务
│   ├── models/
│   │   └── task.py          # Task 数据模型
│   └── storage/
│       └── local.py         # 本地存储
├── tests/
├── pyproject.toml
└── Dockerfile
```

### Frontend 模块
```
frontend/
├── app/
│   ├── page.tsx             # 主页
│   ├── layout.tsx
│   └── api/                 # BFF（可选）
├── components/
│   ├── PromptInput.tsx
│   ├── ProgressBar.tsx
│   ├── VideoPlayer.tsx
│   └── HistoryList.tsx
├── lib/
│   ├── api.ts               # API client
│   └── ws.ts                # WebSocket client
├── package.json
└── tailwind.config.js
```

### 共享
```
shared/
└── prompts/
    ├── system_v1.txt
    └── examples/
        ├── bubble_sort.py
        ├── quick_sort.py
        ├── merge_sort.py
        ├── binary_search.py
        ├── stack.py
        ├── queue.py
        ├── linked_list.py
        ├── bst_bfs.py
        ├── bst_dfs.py
        ├── graph_bfs.py
        └── graph_dfs.py
```

## 📝 关键决策记录 (ADR)

### ADR-001 · LLM 选 DeepSeek-V3
- **决策**：默认 LLM 使用 DeepSeek-V3
- **理由**：
  - 代码能力：HumanEval 82.6%，接近 GPT-4o
  - 价格：输入 ¥1/M tokens（缓存命中），输出 ¥2/M tokens
  - 国内访问无障碍
  - API 兼容 OpenAI，迁移成本低
- **风险**：高峰期可能有速率限制
- **缓解**：备选模型 + 重试 + 排队

### ADR-002 · ManimCE 而非 ManimGL
- **决策**：使用 ManimCE
- **理由**：
  - 社区活跃（GitHub 25k+ stars）
  - 文档完善、API 稳定
  - 易于自动化调用
- **代价**：不支持 OpenGL 实时预览

### ADR-003 · RQ 而非 Celery
- **决策**：用 RQ 做任务队列
- **理由**：
  - 极简（一个 Redis 就行）
  - Python 原生，调试容易
  - MVP 阶段够用
- **未来**：并发量大时换 Celery

### ADR-004 · 沙箱：subprocess + Docker
- **v0.1**：subprocess + 资源限制（CPU/内存/超时）
- **v0.2**：Docker 容器隔离
- **理由**：
  - v0.1 快速验证
  - LLM 生成的代码 + 内网环境 = 风险可控
  - 真上线前必须有 Docker

## 🚨 安全考虑

### LLM 生成代码的风险
| 风险 | 危害 | 缓解 |
|---|---|---|
| 死循环 | 资源耗尽 | subprocess timeout=60s |
| 删除文件 | 数据丢失 | Docker + 只读文件系统 |
| 网络请求 | 信息泄露 | Docker 网络隔离 |
| 内存炸弹 | 系统崩溃 | subprocess ulimit |
| 恶意代码 | 服务器被控 | Docker 容器（v0.2） |

### API 安全
- Rate limiting（每 IP 每分钟 10 次）
- 敏感词过滤（政治/违法）
- DeepSeek API key 不进代码、不进 git
- 视频 URL 加签名

## 📈 性能预算

| 阶段 | 耗时预算 |
|---|---|
| LLM 推理 | < 20s |
| Manim 渲染 | < 30s |
| 上传/IO | < 5s |
| **总** | **< 60s** |

## 🔮 未来扩展

- **v0.5**：异步任务进度推送（SSE 替代 WS）
- **v0.5**：视频转码（多分辨率）
- **v1.0**：多 LLM Provider 切换
- **v1.0**：模板市场（用户贡献 few-shot）
- **v2.0**：实时协同编辑
