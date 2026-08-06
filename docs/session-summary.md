# Session 工作总结

> 最近 2 天（2026-08-06）连续 session 的改动日志。前面的内容已经过时，仅保留"项目背景 / 核心约束"作上下文。

## 项目背景
ThinkCanvas：文字描述 → LLM 生成 Manim 代码 → 渲染成算法/数学动画视频。
- 后端：FastAPI + langchain-openai（MiniMax OpenAI 兼容 API + LiteLLM 适配层）
- 前端：Next.js 15
- 数据：Postgres + SQLAlchemy + Alembic

## 核心约束
- **MiniMax-M3 不原生支持 LangChain 1.x `create_agent` 标准写法** → 走 `langchain-litellm.ChatLiteLLM` 归一化；业务层只看到 `ChatOpenAI`
- **MiniMax 偶发只输出 `[thinking]` 块** → 四层兜底（text-block → 字符串扫描 → 代码栅栏 + 1-shot retry）
- **macOS 用户 TeX 不在 conda env PATH** → `app.main._augment_path_with_tex_bin` 在启动时拼进 PATH
- **academic 风格背景色** → 必须在构造里 `self.camera.background_color = "#FFFFFF"`，改 `config.background_color` 渲染期太晚

## 本次 session 完成的工作

### 1. 基建联通 / 渲染流水线（已稳）
- Next 15 + FastAPI + Postgres + 后端最小 hello 接通前端
- subprocess + 60s timeout 渲染 Manim；产物落 `./media/` + `/media` 静态挂载

### 2. LLM 适配层（2026-08 升级）
- 引入 `langchain-litellm.ChatLiteLLM`，封装为 `ChatOpenAI` 类型
- 业务层用 LangChain 1.x 标准写法：`create_agent(model=, tools=, system_prompt=, response_format=)`
- 手写 agent loop 全部删除（9 个文件 → 4 个核心）

### 3. 多轮对话（conversations + messages 双表）
- 表：`conversations(id, title, style, version, user_id, created_at, updated_at)` + `messages(id, conversation_id, role, content, code, video_url, scene_name, duration_sec, status, error, created_at)`
- 路由：`POST /conversations`（建 + 首轮生成）、`POST /conversations/{id}/refine`（SSE 流式调整）、`GET /conversations`、`GET /conversations/{id}`、`DELETE /conversations/{id}`
- `refine` prompt 三段：[历史用户指令]（最近 6 条）+ [上一版代码] + [本次用户调整要求]
- 单次调整的 token 上界可控：assistant 历史回复一律不喂，只喂"用户说过什么"

### 4. 用户系统（匿名 ULID，无登录）
- `users(id, created_at, last_seen_at, default_style)` 表
- 客户端：localStorage 存 ULID，每次 fetch 带 `X-User-Id` header（`frontend/lib/user.ts`）
- 服务端：ASGI 中间件 `UserIdMiddleware` 从 header 拿用户，缺失/非法回落到 `ANON_USER_ID = "01ANON..."`
- 所有 conversations `user_id NOT NULL`，外键到 users + ondelete CASCADE
- 历史数据迁移：把已有 conversations 全部塞给 `ANON_USER_ID`，不丢数据
- 路由层自动按 user_id 隔离：用户 A 看不了 / 删不了 / 调不了用户 B 的会话

### 5. Studio UI
- 3 栏布局：左历史（可折叠默认收起）+ 中视频/代码（代码默认折叠）+ 右对话面板
- 所有输入收敛到右侧对话面板（首次生成 + 后续调整）
- 乐观 user message：点发送立刻显示，等 SSE 成功再刷状态

### 6. 代码规范化
- `react_coder.py` 删 `_invoke_and_extract` 死别名（39 行，纯薄壳）
- `refine.py` 改走 `builder.build_agent(extra_system_prompt=...)`，不再单独 `create_agent`，两个 agent 路径合一
- `state.py` 改名 `schemas.py`（避免和 LangChain `StateGraph` 撞名）
- 整个 `app/agents/` 目录 docstring 全部改中文
- 单文件 ≤ 300 行（公开模块 ≤ 400 行），超出的 helper 拆出去
- 编码规范见 `docs/coding-guidelines.md`

### 7. 文件 / 模块树（截至本次 session 末尾）

```
backend/app/
├── main.py
├── config.py
├── middleware/
│   └── user_id.py                # X-User-Id 解析
├── agents/
│   ├── react_coder.py            # 单次生成 wrapper（薄壳）
│   ├── refine.py                 # 多轮调整 wrapper（拼 user history）
│   ├── builder.py                # create_agent 工厂 + @lru_cache
│   ├── schemas.py                # CodeOutput Pydantic schema
│   ├── styles.py                 # 风格注册表（3b1b / minimal / academic）
│   ├── tools.py                  # @tool validate / render
│   └── agent_recovery.py         # 四层兜底 + 1-shot retry
├── api/v1/
│   ├── generate.py               # /generate (legacy) + /generate/stream (主用)
│   ├── conversations.py          # /conversations + /refine SSE
│   ├── tasks.py                  # 老 task CRUD（v2 移除）
│   ├── render.py
│   ├── health.py
│   └── readyz.py
├── storage/
│   ├── conversations.py
│   ├── tasks.py
│   └── users.py
├── renderers/manim.py
├── tools/validator.py
├── llm/client.py
└── db/
    ├── session.py
    └── models/
        ├── user.py
        ├── conversation.py
        ├── message.py
        └── task.py

frontend/
├── app/page.tsx
├── components/
│   ├── HistorySidebar.tsx
│   ├── CodeViewer.tsx
│   └── ConversationPanel.tsx
└── lib/
    ├── api.ts                    # fetchJson 默认加 X-User-Id
    └── user.ts                   # ULID 生成 + localStorage
```

### 8. 测试
- pytest：**61 passed**
  - 38 → 40（agent_recovery / refine 单元测试）
  - + 5（user history cap）
  - + 11（user_id middleware）
  - + 5（user-scoped conversation 行为）
- tsc：`./node_modules/.bin/tsc --noEmit` 无错

## 已知 TODO（下一步）

| 项 | 说明 | 优先级 |
|---|---|---|
| **few-shot 库（SQL 检索版）** | 把 `shared/prompts/styles/*.md` 里硬编码的 few-shot 抽到 `few_shots` 表；按 prompt 关键词选 1-2 个拼进 system prompt | 高 |
| **持久化记忆** | `user_preferences`（语言 / 默认风格）+ `user_algorithm_history`（user × 算法 × 时间）；创建会话时塞进 system prompt | 中 |
| **端到端压测** | 3 算法 × 10 次成功率 / 时长（Step 6） | 中 |
| **Worker 异步化** | `rq.enqueue` 解 API 阻塞 | 低（v1.x） |
| **OSS / S3** | 视频存储 | 低 |
