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
| [docs/mvp-scope.md](docs/mvp-scope.md) | v0.1 范围、验收标准、暂不做的事 |
| [docs/architecture.md](docs/architecture.md) | 系统架构、技术选型、数据流 |
| [docs/llm-prompt.md](docs/llm-prompt.md) | LLM Prompt 设计、Few-shot、重试策略 |
| [docs/workflow-design.md](docs/workflow-design.md) | ⭐ LangGraph 状态机、Agent 设计、扩展点 |

## 🛠 当前进度

- [x] 命名：ThinkCanvas
- [x] 环境验证：Manim 渲染管线 OK
- [x] **产品/架构文档完成**（5 份）
- [x] 架构选型定稿：LangGraph + 单 Agent + 可扩展接口
- [x] 本地基础设施：Postgres + Redis（Docker）
- [ ] **建项目骨架** ← 下一步
- [ ] LLM Prompt 调优
- [ ] MVP Web 应用

## 🧪 快速验证

```bash
./verify.sh
# 跑 demos/01_hello.py，输出 mp4
```

## 🤝 贡献

个人项目阶段，欢迎提 Issue。
