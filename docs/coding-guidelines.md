# 编码规范

> 个人项目阶段，先把"几个会反复踩坑的边界"写下来。日后再扩。

## 文件大小

- **单个文件（包括注释）尽量不超过 300 行**。
- 超过时优先把"辅助函数 / helper / 工具"拆出去；不要为了"塞一个文件"硬塞。
- 拆出去的 helper 一般放在同目录新文件，叫 `xxx_helpers.py` / `xxx_utils.py` / 主题名（如 `agent_recovery.py`）。
- 公开入口的模块（被其他模块 `import`）可以稍放宽到 ~400 行；私有 helper 模块也应遵守 300 行上限。
- 测试文件不受此限（多个小 test case 会让它自然变长）。

## 模块边界

- 一个文件做一件事。把"主入口 / 编排"和"具体功能实现"分开。
- 同一个文件内 5+ 个 helper 且互相不依赖主线，应拆出去。
- 同一个文件内 3 层以上 if/try 嵌套超过 2 处 → 抽函数。
- 已被剔除但留着的小 helper（只被本文件引用、且本文件其他地方已不用）→ 删除，不要留作"也许以后用"。

## 命名

- 公开函数：`run_agent` 这种 snake_case，无下划线。
- 内部 helper：`_recover_from_messages` 这种下划线开头。
- 私有 helper 文件（`xxx_helpers.py`）内的函数也可保持无下划线，调用方用 `from .module import helper` 即可。
- 文件名：`xxx_helpers.py` / `xxx_utils.py` / 主题名。不要叫 `misc.py` / `helpers.py` 这种无主题的。

## 改动后自检

- 改完跑一遍测试：`cd backend && python -m pytest -q`。
- Python：`wc -l <file>` 检查行数。
- TypeScript：`frontend && ./node_modules/.bin/tsc --noEmit`。
