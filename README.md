# ThinkCanvas

> **AI 驱动的算法/数学动画生成器**
> 输入文字描述，自动生成 3Blue1Brown 风格的 Manim 视频。

![status](https://img.shields.io/badge/status-MVP%20planning-yellow)
![python](https://img.shields.io/badge/python-3.14-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## 🎯 一句话
让不会 Manim 的人，也能产出专业的算法/数学可视化视频。

## 📚 文档目录

| 文档 | 内容 |
|---|---|
| [docs/product.md](docs/product.md) | 产品定位、目标用户、价值主张 |
| [docs/mvp-scope.md](docs/mvp-scope.md) | v1.0 范围、6 步开发步骤、关键文件清单 |
| [docs/architecture.md](docs/architecture.md) | 系统架构、技术选型、数据流（含 v1.0 实际状态） |
| [docs/tech-stack.md](docs/tech-stack.md) | 技术清单与学习地图 |
| [docs/llm-prompt.md](docs/llm-prompt.md) | LLM Prompt 设计、Few-shot、重试策略 |
| [docs/workflow-design.md](docs/workflow-design.md) | Agent 设计、工作流、扩展点 |
| [docs/session-summary.md](docs/session-summary.md) | 最近 session 的改动总结 |
| [docs/quickstart.md](docs/quickstart.md) | ⭐ 启动命令速查 |

## 🛠 当前进度（v1.0）

- [x] 命名：ThinkCanvas
- [x] 环境验证：Manim 渲染管线 OK
- [x] 产品/架构文档完成（7 份）
- [x] 架构选型定稿：手写 agent loop + LangChain 零件（MiniMax 不支持 tool_calls）
- [x] 本地基础设施：Postgres + Redis（Docker）；Redis 已起但未接业务
- [x] **基建联通**：Next 15 + FastAPI + 后端最小 hello + 接 Postgres
- [x] **Code 流水线**：MiniMax-M3 接入 + 结构化 JSON 输出 + validate_only_retry + 1 个 few-shot
- [x] **渲染流水线**：subprocess + 60s timeout；产物落 `./media/`；`/media` 静态文件挂载
- [x] **Web UI 最小版**：输入 / Generate / 进度条（SSE）/ 视频 / 代码框 / 重渲染
- [ ] **持久化 + 多语言 + 可观测**：user / history 表 + 中英切换 + LangSmith
- [ ] **端到端验证**：3 算法 × 10 次成功率 / 时长
- [ ] **Worker 异步化**：解 API 阻塞（v1.x）

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

## 🤝 贡献

个人项目阶段，欢迎提 Issue。
