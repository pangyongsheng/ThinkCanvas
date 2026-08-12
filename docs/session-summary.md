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
- pytest：**107 passed**（截至 2026-08-08）
  - 61 → 107（含 +46 few-shot / retriever / summarizer / embeddings / backfill）
- tsc：`./node_modules/.bin/tsc --noEmit` 无错

## 2026-08-07 ~ 08-08 增量（补 session 漏掉的部分）

### 9. Few-shot 库 SQL 检索版 ✅ 完成

把 `shared/prompts/styles/*.md` 硬编码的 few-shot 抽到 `few_shots` 表，embedding 检索 + 自动 summarization。

- 新表：`few_shots(id, prompt, code, summary, summary_embedding JSONB, style, source_*, created_at)`
- 迁移：`20260807_add_few_shots.py` / `20260807_add_few_shot_summary.py` / `20260807_add_few_shot_embedding.py`
- 服务端：`app/agents/retriever.py::retrieve_similar_summaries`（cosine 相似度 top_k=2）
- Prompt 拼装：`app/agents/few_shot_prompt.py::with_few_shot_header`（`builder.py:46` 调用）
- 接入路径：`conversations.py:154`（首次生成）+ `conversations.py:364`（refine），都走 `retrieve_similar_summaries`
- HTTP endpoint：`POST /api/v1/few_shots` / `GET /api/v1/few_shots`（详见 `app/api/v1/few_shots.py`）
- **摘要生成**：`app/agents/summarizer.py::summarise_few_shot`（LLM 生成简短 description 作为 embedding 锚点）
- **embedding backfill**：新条目入表后异步跑 `_backfill_embedding` 写 `summary_embedding`

### 10. 前端「👍 收藏为范例」按钮 ✅ 完成

- `ConversationPanel.tsx:153` — 按钮（仅 assistant 消息可见）
- `page.tsx:95` — `handleSaveAsFewShot` → `saveAsFewShot` API
- 用户手动收藏的好例子自动入 `few_shots` 表，retriever 下次会按相似度召回

### 11. LangSmith 集成尝试 → 移除（2026-08-08）

短暂接入了 `TraceIdCapture` callback + `messages.trace_id` 列，但服务端 LangSmith tracing 没真启用（无 `LANGCHAIN_API_KEY`），跑通是死数据。**全部回滚**：

- 删 `app/agents/observability.py`
- 移除 `react_coder.py` 的 callback + result["trace_id"]
- 移除 `message.py` / `agent_step.py` 的 `trace_id` 列、`.env.example` 的 LangSmith section、`config.py` 的 `langchain_*` 字段
- 保留 `add_trace_id` migration（已应用到 DB 的列保留，下次需要可快速回滚）

## 已知 TODO（下一步）

| 项 | 说明 | 优先级 |
|---|---|---|
| **持久化记忆** | `user_preferences`（语言 / 默认风格）+ `user_algorithm_history`（user × 算法 × 时间）；创建会话时塞进 system prompt | 中 |
| **端到端压测** | 3 算法 × 10 次成功率 / 时长（Step 6） | 中 |
| **Worker 异步化** | `rq.enqueue` 解 API 阻塞 | 低（v1.x） |
| **OSS / S3** | 视频存储 | 低 |


### 12. 解耦重构：Web → Agent → DAO（2026-08-08）

按"硬性规范"全面解耦：
- **Web 层** 只做 HTTP 接收 / 鉴权 / 调 AgentService / 渲染 / SSE，不再接触 ORM 与 agent 业务
- **Agent 层** 收拢 agent 业务 + LLM 调用 + 工具捕获；通过 LangChain `AgentMiddleware` 自动落库
- **DAO 层** 单一数据访问入口，路由层严禁直写 SQL

#### 新增
- `backend/app/agents/dao/agent_steps.py` — `AgentStepsDAO.write_steps` 批量落 `agent_steps`；`_serialize_tool_args` 把 dict 序列化成 VARCHAR
- `backend/app/agents/dao/messages.py` — `MessagesDAO`（`append_user_message` / `create_assistant_shell` / `finalize_after_agent` / `attach_video` / `mark_failed`）
- `backend/app/agents/dao/conversations.py` — `ConversationsDAO`（`create` / `get` / `list` / `delete` / `list_user_messages`） + 视频文件清理 helpers
- `backend/app/agents/middleware/persistence.py` — `AgentPersistenceMiddleware`，挂 LangChain 原生 `abefore_agent` / `awrap_tool_call` / `aafter_agent` 钩子
- `backend/app/agents/service.py` — `AgentService` 编排器（`run_initial` / `run_refine` / `attach_video` / `mark_render_failed` / `mark_agent_failed`）

#### 删除
- `backend/app/storage/conversations.py` — 内容已并入 `agents/dao/conversations.py`
- `backend/app/api/v1/generate.py` — legacy `/generate` `/generate/stream` `/generate/agent`；前端没有调用，已被 `/api/v1/conversations` 完全替代
- `backend/app/api/v1/tasks.py` — legacy `/tasks` CRUD；前端没有调用
- `backend/app/storage/tasks.py` — 仅被 `tasks.py` 路由使用
- `backend/tests/agents/test_tasks_crud.py` — 与删掉的 storage 配套
- `backend/tests/storage/test_conversations.py` / `test_user_scope.py` — 旧 storage 测试

#### 修复的 BUG
1. **重复 user 消息写入** — 旧 `ConversationsDAO.create` 顺手建 user 消息，`AgentService.run_initial` 又调 `MessagesDAO.append_user_message`，导致**每次新建会话会插入两条 user 消息**。新方案：`ConversationsDAO.create` 只建会话，user 消息统一由 `MessagesDAO.append_user_message` 创建。
2. **`tool_args` dict → VARCHAR** — 原 `write_agent_steps` 把 dict 直接传 `tool_args`（VARCHAR）会运行时崩。`_serialize_tool_args` 现在落在 `agents/dao/agent_steps.py`，所有 dict/list 调用点自动 JSON 化。
3. **ToolMessage status 默认值** — 原 `if status != "ok"` 把 LangChain 默认的 `"success"` 误标 failed。现在中间件用 `status == "error"` 单向判断（其他一律视为 ok），避开默认值差异。
4. **refine 路径漏写 `agent_steps`** — 原 `/refine` 路由手动调 `write_agent_steps` 但路径不全；首次生成路径则漏配。新方案一处中间件覆盖所有 agent 调用入口，零复制粘贴。
5. **冗余的 ctx["message_id"] 回写** — middleware 把 message_id 写回 runtime.context 但代码从未读取；改为只存实例变量，删除冗余。
6. **同步 middleware 命名冲突** — 基类 `AgentMiddleware.before_agent`/`after_agent` 是 sync 空实现；agent.ainvoke 走 async 路径必须实现 `abefore_agent`/`aafter_agent`/`awrap_tool_call`。原实现用的是 sync 方法名但内部 `async def` —— 工厂链能识别（`m.__class__.awrap_tool_call is not AgentMiddleware.awrap_tool_call`），但接口语义不准。已统一改成 `a` 前缀的 async 方法。

#### 分层架构
```
Web (app/api/v1/conversations.py)
 ├─ 接收 HTTP / 鉴权 / 参数校验
 ├─ 调 AgentService 跑 agent（拿到 AgentRunResult）
 ├─ 调 Manim 渲染
 ├─ 把 video_url 回填（AgentService.attach_video）
 └─ SSE 推送事件
            │
            ▼
Agent (app/agents/service.py + middleware/persistence.py)
 ├─ AgentService.run_initial / run_refine — 业务编排
 ├─ AgentPersistenceMiddleware
 │   ├─ abefore_agent  → MessagesDAO.create_assistant_shell
 │   ├─ awrap_tool_call → AgentStepsDAO.write_steps（落库 + SSE）
 │   └─ aafter_agent   → MessagesDAO.finalize_after_agent
 └─ invoke_with_recovery — LLM 输出兜底
            │
            ▼
DAO (app/agents/dao/*.py)
 ├─ AgentStepsDAO  — agent_steps 表
 ├─ MessagesDAO    — messages 表
 └─ ConversationsDAO — conversations 表 + 视频文件清理
```

#### 验证
- `pytest -q`：**100 passed**（100 个用例覆盖原 107 - 删除 7 个 storage/tasks 相关）
- `mypy app/agents/...`：本次重构的 6 个文件**零错误**（其余错误为历史遗留）
- `app.main.app.openapi()`：路由列表只剩 conversations/few_shots/health/readyz/render，**不再有** `/generate`、`/tasks`


### 13. 「成功一次 失败一次」BUG 修复（2026-08-09）

现象：同一会话连续调 refine，LLM 输出不稳定时第一次出图、第二次失败。失败率高。

根因：`invoke_with_recovery` 旧版只在 LLM 输出「thinking + 空 text」这种明显截断时才重试一次。MiniMax-M3 在长 refine prompt + 用户指令含糊时，**输出可能既不截断、也完全无 code** —— 4 层兜底（text-block / aggressive scan / python fence）全失败，旧代码不重试直接放弃。

修复：
- `backend/app/agents/agent_recovery.py` — 重写重试循环：从「截断才重试」改成「`extract_from_result` 拿不到 code 就重试」，最多 3 次（原 + 2 retry）
- `backend/tests/agents/test_refine.py` — 加 2 个测试覆盖新行为：`test_refine_retries_when_extraction_completely_fails` / `test_refine_gives_up_after_3_attempts`

#### 验证
- `pytest -q`：**102 passed**（100 + 2 新增）
- `tests/agents/test_refine.py::test_refine_retries_when_output_looks_truncated` 仍 PASS（旧 truncation 场景被新逻辑覆盖）
- 监控日志关注新事件 `agent_recovery.no_code_attempt_N` — 出现频率越高，说明 LLM 越不稳定，需要进一步优化 prompt

### 14. 删除对话 500 修复（2026-08-09）

现象：`DELETE /api/v1/conversations/{id}` 返回 500。

根因：原 `ConversationsDAO.delete` 用 `session.get(Conversation, id)` 拿到对象后，**靠 ORM cascade 级联删除 messages**。async 路径上 ORM cascade 触发 lazy load 时容易踩到 `MissingGreenlet`，且 cascade + DB-level `ON DELETE CASCADE` 同时启用会引入顺序歧义。

修复 (`backend/app/agents/dao/conversations.py:140-178`)：
- 改用 `selectinload(Conversation.messages)` 显式预加载 — 避免后续 cascade 时再触发 lazy load
- 用 `bulk DELETE` 直接按 `conversation_id` 删 messages → DB 自动 CASCADE 删 agent_steps
- 再 bulk DELETE conversation — 双向 CASCADE 兜底，少一层 ORM 状态机出错点

测试 (`backend/tests/agents/test_conversations_dao.py`)：5 个用例覆盖 4 种场景（无找到 / 用户不匹配 / 正常 / 无消息 / 无视频）

#### 验证
- `pytest -q`：**107 passed**（102 + 5 新增）

### 15. 长期记忆 / 用户档案（2026-08-09）

让 agent 跨会话记住用户：偏好（语言 / 默认风格 / 自定义说明）+ 算法历史（做过什么）+ 反馈（👍/👎）。新会话开局时把这段塞进 system prompt。

#### 新增

**ORM models** (`backend/app/db/models/`)
- `user_preference.py` — 1:1 挂 users，存 language / default_style / extra_instructions
- `user_algorithm_history.py` — user × algorithm 去重轨迹，`UNIQUE(user_id, algorithm_name)` + embedding 用于相似度合并
- `user_feedback.py` — 用户对 assistant message 的 verdict (liked/disliked) + note

**DAO 层** (`backend/app/agents/dao/`)
- `user_preferences.py` — `UserPreferencesDAO`（get / upsert / reset）用 sentinel 默认区分"没传"和"传 None 清空"
- `user_algorithm_history.py` — `UserAlgorithmHistoryDAO`（`upsert_by_name` 走 `INSERT ... ON CONFLICT DO UPDATE`，`list_recent` / `merge_into`）
- `user_feedback.py` — `UserFeedbackDAO`（write / list_recent / get_latest_for_message）

**Memory 层** (`backend/app/agents/`)
- `memory.py` — `build_memory_block(session, user_id)` 召回偏好+历史+反馈，拼成可塞 system prompt 的 markdown 段；空数据自动空字符串
- `algorithm_extractor.py` — 一次轻量 LLM 调用抽 (algorithm_name, embedding)；失败回落到 "general"，绝不抛

**Service 集成** (`backend/app/agents/service.py`)
- `_run_agent` 加 `user_id` 参数 → `build_memory_block` 拼到 `extra_system_prompt` 末尾
- 跑完后 `_schedule_algorithm_capture` fire-and-forget：开新 session，调 extractor，upsert 到 history

**API 层** (`backend/app/api/v1/preferences.py`)
- `GET /api/v1/preferences` — 读偏好
- `PUT /api/v1/preferences` — 部分字段 upsert
- `DELETE /api/v1/preferences` — 重置（幂等）
- `POST /api/v1/feedback` — 写一条 👍/👎，message_id 校验防横向越权

**Migration** (`backend/alembic/versions/20260809_add_user_memory.py`)
- 3 张新表 + 索引 + UNIQUE 约束
- 顺带把 alembic_version.version_num 放宽到 VARCHAR(64)

#### 测试

- `tests/agents/test_user_memory_dao.py` — 9 个 DAO 用例（sentinel 默认、upsert 合并、reset 边界）
- `tests/agents/test_memory.py` — 9 个拼装用例（空数据 / 单段 / 全段 / 字段跳过）
- `tests/agents/test_algorithm_extractor.py` — 7 个解析 + fallback 用例（JSON / fence / 错误输入）

`pytest -q`：**132 passed**（107 + 25 新增）

#### 数据流

```
新会话
  POST /conversations
    ↓
  AgentService.run_initial
    ├─ build_memory_block 召回偏好 + 历史 + 反馈
    ├─ 拼到 system prompt 末尾
    ├─ build_agent + invoke_with_recovery
    └─ 后台 task: extract_algorithm_name → upsert_by_name

用户 👍/👎
  POST /feedback { message_id, verdict, note }
    ↓
  UserFeedbackDAO.write 落库，下次会话时被 memory.py 召回
```

### 16. 长期记忆 v2 — LLM-curated memories（2026-08-09）

**取代 v1 的简单表拼接**（v1 把 user_algorithm_history / user_feedback / user_preferences 原样塞 prompt，太糙）。

v2 架构：

```
原始事件                          curator (LLM)                user_memories
─────────────────                ─────────────                ────────────────
generation (prompt+code+status)   ─┐
feedback (liked/disliked+note)     ├→  读现有 memories + 事件      add / reinforce /
preference (用户改的语言等)        ┘   调 LLM 输出 JSON patch  ─→  update / remove
```

**新表 `user_memories`**（替换 v1 三个表直接喂 prompt 的角色）：

```
user_memories (
  id, user_id, category (preference/pattern/avoidance/style_hint),
  insight TEXT,            -- LLM 提炼的一句话洞察
  confidence FLOAT,        -- 0~1，多次 reinforce 后升高（封顶 1.0）
  evidence_count INT,      -- 多少事件支持这个洞察
  superseded_by_id,        -- 被新洞察覆盖时旧行指针
  status (active/decayed), -- decayed = curator 判定不再成立
  created_at, last_reinforced_at
)
```

**MemoryCurator** (`backend/app/agents/memory_curator.py`)

- 输入：MemoryEvent（kind=generation/feedback/preference + summary + extra）
- 流程：list_all_active → 拼 user_msg → 调 LLM（OpenAI JSON 模式） → parse actions → apply patch
- patch types：add / reinforce / update / remove，每种对应 DAO 一个方法
- 失败兜底：LLM 异常 / JSON parse 失败 / 任何 action 异常都只 log，不抛

**Prompt 拼接 (`memory.py` v2)**

- 只读 `user_memories.list_active(user_id)`，按 confidence × recency 倒序取前 15 条
- 按 category 分 4 段（用户偏好 / 用户行为模式 / 应避免的事 / 风格提示）
- 空数据返回空字符串，不污染 prompt

**Service 集成 (`backend/app/agents/service.py`)**

- `_run_agent` 末尾：`_schedule_memory_curator` —— fire-and-forget task，开新 session，调 curator
- 公开 `schedule_feedback_curator` / `schedule_preference_curator` —— 路由层在 POST /feedback 和 PUT /preferences 末尾调

**API**

- 新增 `GET /api/v1/memories` —— 调试用，返回当前用户的 active memories 列表
- `POST /api/v1/feedback` 末尾自动调 curator
- `PUT /api/v1/preferences` 末尾自动调 curator

**新增文件**

- `backend/app/db/models/user_memory.py` — ORM + CATEGORIES 常量
- `backend/app/agents/dao/user_memories.py` — DAO（list_active / add / reinforce / update_insight / remove）
- `backend/app/agents/memory_curator.py` — LLM curator
- `backend/alembic/versions/20260809_add_user_memories.py` — migration
- `tests/agents/test_user_memories_dao.py` — 7 个 DAO 用例
- `tests/agents/test_memory_curator.py` — 12 个 curator 用例（parse / format / apply）

**修改**

- `backend/app/agents/memory.py` — 重写为只读 user_memories，按 category 分段
- `backend/app/agents/service.py` — `_schedule_algorithm_capture` → `_schedule_memory_curator` + 暴露 feedback/preference curator hooks
- `backend/app/api/v1/preferences.py` — PUT/POST 末尾调 curator；新增 GET /memories
- `tests/agents/test_memory.py` — 重写为 4 个新测试

**验证**

- `pytest -q`：**146 passed**（132 + 14 新增 / 重写）
- 路由：`/api/v1/memories` 已注册

**用户验证方式**

1. 重启后端（应用 migration）
2. 跑几次生成（每次都会触发 generation event → curator 加 memory）
3. `curl http://localhost:8000/api/v1/memories -H "X-User-Id: <你的id>"` 看 curator 提炼了什么
4. 给条 👎 + 注释，看下次会话 prompt 里出现对应 avoidance 类 memory

### 17. LangGraph Supervisor 编排框架 P1（2026-08-10）

把当前单 `create_agent` 跑全活的模式换成 LangGraph Supervisor 模式。
P1 范围只挂 1 个 worker（`coder`），Supervisor LLM 只做"调 coder / 收工"
的最小决策。P2 起会往 `agents=[...]` 列表里塞 Reviewer / Script Designer /
Fixer，结构不动。

#### 改了什么

**新增**：
- `backend/app/agents/supervisor.py` — `build_supervisor()` + `build_coder_worker()` 工厂
- `backend/tests/agents/test_supervisor.py` — 11 个测试（worker 构造 / supervisor 构造 / 中间件兼容 state-context 双路径）

**修改**：
- `backend/app/agents/middleware/persistence.py` — `abefore_agent` 走 `_resolve_conversation_id` / `_resolve_on_event` 兼容 state / context 双路径（Supervisor 不会透传 `runtime.context`，必须能走 state 兜底）
- `backend/app/agents/service.py::_run_agent` — `build_agent` → `build_supervisor`；`supervisor_input` 把 `conversation_id` / `on_event` 塞进 state

#### 架构

```
Supervisor（LLM 决策：调 coder / 收工）
  └─ coder（ReAct worker，validate + render tools + AgentPersistenceMiddleware）
```

Supervisor 节点：
- `__start__` → `supervisor` → `coder` → `supervisor` → 结束
- 节点名来自 `langgraph_supervisor.create_supervisor`

#### 关键决策

1. **Coder worker 仍带 `response_format=CodeOutput`** — Supervisor 的 `output_mode="full_history"` 让 messages 链能走 `extract_from_result` 兜底
2. **middleware 只挂 Coder 不挂 Supervisor** — 落库 / SSE 是 worker 行为，supervisor 自身不需要
3. **不缓存 CompiledStateGraph** — Supervisor 的 worker 列表 / prompt 每次都变（few-shot / extra），缓存命中率低
4. **context 兼容双路径** — 老路径 `ainvoke(context={...})` 仍能跑；Supervisor 路径走 `state["conversation_id"]` 兜底

#### 验证

- `pytest -q`：**157 passed**（146 + 11 新增）
- `build_supervisor().nodes`：`['__start__', 'supervisor', 'coder']` ✓
- 现有 conversations / refine 集成测试不动也都过（`AgentService._run_agent` 路径已切换）

#### P2-P4 计划

| 阶段 | 加什么 |
|---|---|
| P2 | Reviewer worker（Coder → Reviewer 循环，`code_round` 控上限 2 轮） |
| P3 | Script Designer + ask_human worker（入口分流 + 用户确认脚本） |
| P4 | Fixer worker（render 失败回灌修代码） |

每阶段 P 都在 supervisor.py 的 `agents=[...]` 列表里加新 worker；Supervisor
的 prompt 增对应决策规则；P2 起需要扩 SupervisorState 字段（如
`code_round` / `fix_round` / `script` / `script_confirmed`）。

#### 修 P1 引入的两个 BUG（2026-08-10 晚）

**BUG 1 · `InFailedSQLTransactionError`**

`build_memory_block` 吞异常时没 rollback session。SELECT 失败的
session 停在 failed transaction 状态，下一次 `commit()` 直接报
`asyncpg.exceptions.InFailedSQLTransactionError`。

修：
- `app/agents/memory.py::build_memory_block` 的 except 块加
  `await session.rollback()` 把 session 救回来
- `app/agents/service.py::_run_agent` 整个 `supervisor.ainvoke` 用
  try/except 包，失败时 rollback + mark_failed 写回 assistant 消息
- `tests/agents/test_memory.py` 加 `test_dao_exception_triggers_session_rollback`

**BUG 2 · `greenlet_spawn has not been called`**

`langgraph_supervisor.create_supervisor` 包裹 worker 时不传
`runtime.context`（subgraph 调用），worker 子图的 greenlet 边界在
asyncpg / MiniMax-M3 组合下报 "greenlet_spawn has not been called" —
中间件的 context 路径失效，state 兜底又被 supervisor 的 state schema
拒掉（AgentState 不允许业务字段）。

修（**P1 简化方案**）：
- `app/agents/supervisor.py::build_supervisor` 改走 Coder 直接路径，
  P1 阶段不包 `create_supervisor`
- 1 个 worker 时 supervisor LLM 决策层没价值（永远"调 coder"）
- 少一次 LLM 调用、少一层 subgraph 边界
- P2+ 加 Reviewer / Script Designer / Fixer 时切回 `create_supervisor`，
  那时再扩 SupervisorState 显式包含 `conversation_id` / `code_round`
  等业务字段，并保持 context 透传修复

**测试**：158 passed（157 + 1 memory rollback 用例）

**重启后行为**：refine 走 Coder 直接路径，context 正常透传，跟重构前
完全等价。出图流程不变。

### 18. P2 · Reviewer worker 上线（2026-08-10）

Coder 写完代码后加一层独立审查。审查不通过就让 Coder 重写，
最多 2 轮（Coder 最多跑 2 次：首轮 + 1 次 retry）。

**架构（graph-driven，不用真 Supervisor）**：

```
[__start__] → Coder → Reviewer ── ok 或 round≥2 ─→ [__end__]
                              └─ 不ok && round<2 ─→ Coder (附 feedback)
```

P2 流程固定（Coder ↔ Reviewer 循环），用 `StateGraph` + 条件边比
`create_supervisor` (LLM 决策) 更可预测，避开之前 P1 的
`create_supervisor` 包裹 worker 的 greenlet 边界问题。
P3+ 加 Script Designer 入口分流时再上真 Supervisor。

**新增**：
- `backend/app/agents/reviewer.py` — `CodeReview` Pydantic schema +
  Reviewer system prompt + user message 拼装 helper
- `backend/app/agents/supervisor.py` — 改 P2：StateGraph 含 coder /
  reviewer 两个 node + 条件边 + `SupervisorState` TypedDict +
  `MAX_CODE_ROUNDS = 2`

**修改**：
- `backend/app/agents/service.py::_run_agent` — 不再走 `invoke_with_recovery`
  包裹（Coder 节点内部已自带），直接 `supervisor.ainvoke` 后从 P2 state 抽
  `code` / `thought` / `scene_name` / `review` / `code_round`
- `backend/tests/agents/test_supervisor.py` — 改 P2：18 个测试覆盖
  worker 构造 / supervisor 图结构 / Reviewer helpers / middleware 兼容

**State schema（`SupervisorState`）**：
- `messages` — 标准（add_messages 归约）
- `conversation_id` / `on_event` — 给中间件 / SSE
- `code` / `thought` / `scene_name` — Coder 输出
- `review` — Reviewer `CodeReview` 对象
- `code_round` — 0, 1, 2（cap 在 `MAX_CODE_ROUNDS`）
- `previous_feedback` — 上一轮 review.feedback，Coder 第二轮拼到 extra prompt

**Reviewer 审查维度**（不替用户审"好不好看"）：
- Manim API 用对没（import / Scene / construct / play / wait）
- 危险调用（os / subprocess / while True / open / 网络）
- 代码完整不截断
- AST 没语法错

**验证**：
- `pytest -q`：**165 passed**（158 + 7 新增）
- `build_supervisor().nodes`：`['__start__', 'coder', 'reviewer']` ✓
- mermaid 图含 `coder` / `reviewer` / 条件边 ✓

### 19. P3 · Script Designer 入口分流（2026-08-10）

复杂需求先出脚本给人确认，简单直接走 Coder。Supervisor
图加 Script Designer 节点 + 入口分诊节点 + 路由按 phase 派发。

**架构（StateGraph）**：

```
[__start__] (phase=scripting) → script_decision
                                       ↓ need_script?
                              ┌────────┴────────┐
                              ↓                  ↓
                       script_designer        coder (跳到 P2 流程)
                              ↓
                         [__end__]   (停在这等用户确认)

[__start__] (phase=coding) → coder → reviewer (P2 流程)
```

**新增**：
- `backend/alembic/versions/20260810_add_script_phase.py` — 加
  conversations.phase / current_script JSONB / messages.phase + 索引
- `backend/app/agents/script_designer.py` — `Scene` / `SceneScript`
  Pydantic schema + Script Designer prompt + user message helper
- `backend/tests/agents/test_script_designer.py` — 8 个 schema / helper 测试
- `backend/app/api/v1/conversations.py` — 新增
  `POST /conversations/{id}/confirm` 续跑 endpoint（同步返回 code）

**修改**：
- `backend/app/db/models/conversation.py` — Conversation 加 phase
  / current_script 字段（current_script 用 `JSONB().with_variant(JSON, "sqlite")`
  兼容 SQLite 测试）
- `backend/app/db/models/message.py` — Message 加 phase 字段
- `backend/app/agents/supervisor.py` — 扩 SupervisorState 加
  phase / current_script / script_confirmed / need_script；
  加 script_decision / script_designer 两个 node + 三个
  condition router；入口按 phase 决定从哪起跑；
  解析失败 fallback（decision → need_script=True；designer → phase=coding）
- `backend/app/agents/service.py` — `AgentRunResult` 加
  phase / script / need_script 字段；`run_initial` 默认 phase=scripting；
  新增 `run_after_confirm` 续跑入口；`_run_agent` 返回 (msg, state) 元组
- `backend/app/agents/dao/conversations.py` — 加 `set_phase` /
  `update_after_run` DAO 方法

**SSE 事件**（P3 新增）：
- `script_ready` — 脚本生成完推给前端，含 `script` dict + `need_script` 布尔
- 前端看到后弹脚本确认面板，用户点"OK" / "改一下"
- 用户点确认 → POST `/conversations/{id}/confirm` → 续跑 phase=coding

**降级策略**：
- Script Designer 解析失败 → `phase=coding`（跳过脚本直接进 Coder）
- Script Decision 解析失败 → `need_script=True`（按复杂走，宁可多走一步）
- 与 Reviewer 解析失败 fallback `ok=True` 对称

**验证**：
- `pytest -q`：**173 passed**（165 + 8 新增）
- P3 supervisor 节点：`['__start__', 'script_decision', 'script_designer', 'coder', 'reviewer']` ✓
- `build_supervisor(phase="scripting")` / `build_supervisor(phase="coding")` 都跑通

**重启后行为**：
- 第一次跑（前端不传 phase）：默认 phase=scripting，先过 Script Designer
- 复杂需求 → 出脚本 → SSE 推 `script_ready` → 前端弹面板
- 简单需求 → Script Designer 判定不需脚本 → 直接进 Coder → 视频
- 用户点确认 → POST `/conversations/{id}/confirm` → phase=coding → 出视频

## 19. P3 BUG 修复 — `run_initial` scripting 阶段不要求 assistant_message

**症状**：用户发"解释傅里叶变换"（概念性内容，走 Script Designer
路径），后端报 `RuntimeError: AgentService: no assistant message
after run_initial (conversation=...)`。

**根因**：P3 默认 `phase=scripting`，图走
`script_decision` → `script_designer` → `__end__`（停在那等用户确认）。
**Coder 从未执行**，因此 `AgentPersistenceMiddleware.abefore_agent`
不触发，assistant 消息壳没建。

`service.run_initial` 里 `_require_message(...)` 硬性要求
`assistant_msg is not None`，脚本阶段本来就不该有 — 抛 RuntimeError。

**修复**：
- `backend/app/agents/service.py::AgentRunResult.assistant_message`
  类型改 `Optional[Message]`
- `backend/app/agents/service.py::run_initial` — `final_phase ==
  PHASE_SCRIPTING` 时不再 `_require_message`，`assistant_message`
  可为 `None`；`code` / `scene_name` 也加 None-safe 取值
- `backend/app/agents/service.py::_require_message` docstring 更新
  说明"只对 coding 阶段断言"

**测试**：
- `backend/tests/agents/test_service_run_initial.py`（新增 3 用例）
  * `test_run_initial_scripting_phase_allows_none_assistant` —
    脚本阶段 `assistant_msg=None` 不抛错，正常返回 `script`
  * `test_run_initial_coding_phase_requires_assistant` — coding
    阶段缺 assistant_msg 仍按原逻辑抛 RuntimeError（防御回归）
  * `test_run_initial_coding_phase_with_assistant_succeeds` —
    coding 阶段正常路径

**验证**：`pytest -q` → **176 passed**（173 + 3）

**前端/路由层影响**：零。`POST /conversations` 路由 runner 看到
`phase == "scripting" and script` 走 `script_ready` SSE 分支并 return，
从不访问 `assistant_message.id`；coding 阶段 `_require_message`
已保证 `assistant_message` 不为 None。

## 20. P3 BUG 修复 — 脚本阶段前端 Promise 永远 pending

**症状**：用户发概念性需求（"傅里叶积分变化" 等），脚本生成后
页面卡死 30 分钟不响应。后端处理几秒就完成，但前端 spinner
一直转。

**根因**：`subscribeCreateConversation` 里 Promise 只在收到
`done` 或 `failed` 事件时 resolve/reject。后端 `script_ready`
事件发了之后**没发 done**就 return，前端 Promise 永远 pending，
`busy` 状态卡住。`CreateStreamHandlers` 里也没 `scriptReady` handler，
事件本身也被忽略。

**修复**：
- `backend/app/api/v1/conversations.py` — `script_ready` 后
  补发 `done(status="script_ready", ...)`，payload 含脚本；
  Promise 能正常 resolve
- `frontend/lib/api.ts` —
  * `CreateConversationResult` 加 `status` / `script` / `need_script` 字段
  * 新增 `ScriptDraft` / `SceneDraft` 类型
  * 新增 `confirmConversation(conversationId)` 函数封装
    `POST /conversations/{id}/confirm`
- `frontend/app/page.tsx` —
  * `Status` 类型加 `"script_ready"`
  * 新增 `pendingScript` state
  * `done` handler 识别 `status === "script_ready"` → 设
    `pendingScript`、显示脚本面板、不调用 `getConversation`
  * `handleConfirmScript` — 调 `confirmConversation`，刷
    activeConversation，状态切 `done`
  * `handleRejectScript` — 清 pendingScript，让用户重写 prompt
  * `ScriptReviewPanel` 组件 — 标题/概念/总时长/风格 +
    每个分镜的视觉/动画/文字标注 + 右上角"改一下"/"确认并生成"按钮
  * `reset()` 一并清 pendingScript

**验证**：
- 前端 `tsc --noEmit` 通过
- 后端 `pytest -q` → **176 passed**（无回归）

**用户流程**（脚本阶段）：
1. 发概念性需求 → 后端判定需脚本 → 生成脚本
2. 主区域弹 `ScriptReviewPanel`（不再是无限 spinner）
3. 用户可点：
   * **确认并生成** → POST `/conversations/{id}/confirm` →
     Coder 续跑 → 出视频
   * **改一下** → 清面板 + 状态，用户在右侧输入框重写需求

## 21. P3 BUG 修复 — confirm 路径 500（`build_supervisor` 没收到 phase）

**症状**：用户脚本确认后点"确认并生成"，`POST /conversations/{id}/confirm`
返回 500。后端日志：`agent error: AgentService: no assistant message
after run_after_confirm`。

**根因**：`AgentService._run_agent` 收到 `phase=PHASE_CODING`（从
`run_after_confirm` 传），但**没透传给 `build_supervisor`**。Supervisor
默认 `phase=PHASE_SCRIPTING`，入口条件边：
```python
lambda state: "coder" if phase == PHASE_CODING else "script_decision"
```
闭包里的 `phase` 永远是 `"scripting"`，confirm 路径仍先跑 `script_decision`
→ `script_designer`（LLM 出脚本或 fallback）→ `__end__`，Coder
没机会跑 → middleware 没建 assistant 壳 → `_require_message` 抛
RuntimeError → 500。

**修复**：`backend/app/agents/service.py::_run_agent` —
`build_supervisor(...)` 加 `phase=phase` 参数透传。

**测试**：
- `test_run_after_confirm_passes_coding_phase_to_run_agent` —
  spy `_run_agent` 验证收到 `phase=PHASE_CODING`
- `test_run_agent_signature_passes_phase_to_build_supervisor` —
  静态扫描 `_run_agent` 源码断言 `build_supervisor(...)` 调用里
  有 `phase=phase`（防漏传回归成本最低）
- `test_run_initial_default_phase_scripting` — 默认 phase 验证

**验证**：`pytest -q` → **179 passed**（176 + 3）

## 22. P3 handlePick 漏恢复 pendingScript — 历史"脚本待确认"会话看着像卡死

**症状**：用户在左侧列表点开 `phase="scripting"` 的历史会话（之前
出过脚本、没确认的），前端显示**空白 CodeViewer**，半小时像"卡死"。
实际上脚本一直都在库里，只是前端没显示出来。

**根因**：双层缺字段
- 后端 `ConversationDetailOut`（`app/api/v1/conversations.py:73`）只
  序列化 id/title/style/version/messages，**没带 `phase` 和 `current_script`**
- 前端 `ConversationDetail` 类型没这俩字段，`handlePick` 加载完后只能
  当"已完成"会话显示 → CodeViewer 空白 → 用户看着像挂了

**修复**（极简，3 处）：
- `backend/app/api/v1/conversations.py`
  - `ConversationOut` 加 `phase: str = "coding"`
  - `ConversationDetailOut` 加 `current_script: dict | None = None`
  - `_conv_to_out` 把 `c.phase` 带上
- `frontend/lib/api.ts`
  - `ConversationRecord` 加 `phase: string`
  - `ConversationDetail` 加 `current_script?: ScriptDraft | null`
- `frontend/app/page.tsx`
  - `handleCreateFirst` 的 optimistic 对象补 `phase/current_script`
    字段（不然 TS 编译不过）
  - `handlePick` 加载完后：如果 `detail.phase === "scripting" &&
    detail.current_script` → `setPendingScript` + `setStatus("script_ready")`，
    ScriptReviewPanel 重新挂出来让用户继续确认

**验证**：
- `tsc --noEmit` 通过
- `pytest -q` → **179 passed**

**用户操作**：浏览器 Cmd+Shift+R 硬刷新前端，再点历史会话，脚本面板
会重新挂出来。点「确认并生成」走 POST /confirm 即可继续。

## 23. confirm 500 — `_route_after_reviewer` 返了 dict，LangGraph 直接炸

**症状**：用户在脚本面板点「确认并生成」→ 后端 `POST /confirm` 500，
traceback 末尾：

```
File ".../langgraph/graph/_branch.py", line 203, in _finish
    r if isinstance(r, Send) else self.ends[r] for r in result
                                  ~~~~~~~~~^^^
TypeError: cannot use 'dict' as a dict key (unhashable type: 'dict')
During task with name 'reviewer' ...
```

**根因**：`_route_after_reviewer`（`app/agents/supervisor.py:246`）
函数签名是 `Literal["coder", "__end__"]`，但**失败分支最后 `return`
写成了 state update dict**：

```python
return {"previous_feedback": review.feedback or "...", "code_round": ...}
```

LangGraph 把 router 的返回值当 `ends` dict 的 key 用，dict 不可 hash
→ TypeError。这是上次 P2 加 Reviewer�Coder 循环时埋的。

**修复**（极简，2 处）：
- `app/agents/supervisor.py::_reviewer_node` — 不通过时直接写
  `previous_feedback` 到 state update（reviewer node 的本职）
- `app/agents/supervisor.py::_route_after_reviewer` — 只返 `"coder"`
  或 `"__end__"`，不再返 dict

**新增 3 个回归测试**（`tests/agents/test_supervisor.py`）：
- `test_route_after_reviewer_never_returns_dict` — 6 个 state 组合
  全部断言返回值是 `str` 且 ∈ {`"coder"`, `"__end__"}`
- `test_reviewer_node_writes_previous_feedback_on_failure` — 失败时
  state update 里有 `previous_feedback`
- `test_reviewer_node_no_previous_feedback_on_success` — 通过时不污染

**验证**：
- `pytest -q` → **182 passed**（179 + 3）

## 24. confirm 半小时没视频 — handler 漏渲染 + attach_video

**症状**：脚本面板点「确认并生成」→ 后端 200 OK 返回 `{code, scene_name}`，
前端跳"脚本已确认，生成完成" → 左侧 CodeViewer 显示「视频还没渲染好」半小时。
Network 面板 confirm 200 但 video_url 永远 null。

**根因**：`POST /conversations/{id}/confirm` handler（`app/api/v1/conversations.py:240`）
只跑了 agent、返了 `{code, scene_name, conversation_id}` 就结束，**没调
`render_code`、没 `attach_video`**。前端 `handleConfirmScript` 紧跟着
`getConversation(cid)` 重新拉的 fresh 里 assistant.video_url 仍然是 null
（middleware finalize 时只填 code，video 还得路由层写）。

**修复**：跟 `create_conversation` 同款 5 步走：
- 提取 `scene_name`（fallback 到 `extract_scene_name(code)`）
- `await render_code(code, scene_name)`
- 失败 → `mark_render_failed` + 抛 500
- 成功 → `to_video_url(path)` + `attach_video(message_id, video_url, duration)`
- 响应里多带 `video_url` + `duration_sec`，前端 `ConfirmConversationResult` 类型同步加

**前端**：`lib/api.ts` `ConfirmConversationResult` 加 `video_url?` / `duration_sec?`
（`handleConfirmScript` 不用改 — 它后面还会 `getConversation` 重新拉，attach
后 fresh 已经有 video_url 了）。

**新增 4 个回归测试**（`tests/api/test_confirm_renders.py`）：
- `test_confirm_calls_render_code` — handler 必须调 render_code
- `test_confirm_calls_attach_video` — 必须 attach_video
- `test_confirm_returns_video_url` — 响应带 video_url
- `test_confirm_marks_render_failed_on_error` — 渲染失败必须 mark_render_failed

**验证**：`pytest -q` → **186 passed**（182 + 4）
