# 05 · 工作流与 Agent 设计

> 反映 v1.0 **当前**实际状态（2026-08 P3 更新）。
>
> 关键演进：从"标准 `create_agent` + 单 agent"升级为 **LangGraph `StateGraph` Supervisor**（入口分诊 + Script Designer + Coder ↔ Reviewer），并加了**长期记忆**和 **Memory Curator**。

---

## 🎯 设计目标

1. **流程可控**：每一步出错都能定位、能修
2. **可扩展**：加新节点 / 新 Agent 不破坏现有图
3. **可调试**：节点级 trace（agent_steps）落库 + `g.draw_mermaid()` 可视化
4. **可重试**：错误能自动恢复（Coder 内部 4 层兜底 + 节点间循环）
5. **厂商中立**：业务代码不绑死 MiniMax（`langchain-litellm` 适配）
6. **用户友好**：复杂 / 抽象 prompt 先出脚本给用户确认，避免黑盒失败

---

## 🧠 选型结论（v1.0 当前）

| 候选 | 决策 | 原因 |
|---|---|---|
| **LangGraph `StateGraph` Supervisor** ✅ | **当前在用** | 多节点编排 + 条件边 + 中间件统一持久化 + 可视化 |
| 单 `create_agent`（v1.0 早期） | ❌ 已升级 | 没法做入口分诊 / Reviewer 自检 / 脚本确认 |
| `create_react_agent`（旧） | ❌ | LangChain 1.x 之前的过渡 API |
| 自研状态机 | ✗ | 几百行样板，LangGraph 已经做了 |
| LangGraph 真 Supervisor（subgraph 调用） | ❌ | 之前试用踩了 greenlet BUG；用 StateGraph 条件边等效 |

### 为什么 StateGraph 条件边而不是真 Supervisor

- 真 `create_supervisor`（langgraph-supervisor 包）把 worker 当 subgraph 调用，
  runtime context / middleware 透传有坑，SQLAlchemy async 报 greenlet error
- StateGraph 条件边 + 普通 node 走完整 path，等效于 Supervisor，**还没透传坑**
- 后期要扩成多 worker 时再评估真 Supervisor

---

## 🔄 实际工作流（v1.0 当前 — Supervisor StateGraph）

### 整体流程图

```
[__start__]
     │
     ▼
┌──────────────┐
│ entry_router │ ◀── 读 state["phase"] 或 state["script_confirmed"]
└──────┬───────┘
       │
       ├─ phase=coding / script_confirmed → coder
       │
       └─ phase=scripting (默认) → script_decision
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  _script_decision_node │ ◀── LLM 决策 need_script
                              └──────────┬───────────┘
                                         │
                       ┌─────────────────┴─────────────────┐
                       ▼                                   ▼
            ┌────────────────────┐                  ┌────────────┐
            │  _script_designer  │                  │   coder    │
            │   (出 SceneScript  │                  │ (create_   │
            │    JSON 给用户)    │                  │  agent)    │
            └────────┬───────────┘                  └─────┬──────┘
                     │                                    │
                     ▼                                    ▼
              ┌──────────────┐                  ┌────────────────┐
              │ __end__      │                  │   reviewer     │
              │ (等用户确认) │                  │ (CodeReview    │
              └──────────────┘                  │    结构化输出) │
                                                └──────┬─────────┘
                                                       │
                            ┌──────────────────────────┴──────────────────┐
                            ▼                                             ▼
                     __end__（reviewer.ok                                coder
                     或 round >= MAX）                                  （写 feedback 续跑）
```

### 节点职责

| 节点 | 实现 | 职责 | 输出 |
|---|---|---|---|
| **entry_router** | `lambda state: "coder" if phase==PHASE_CODING else "script_decision"` | 根据 phase 决定从哪起 | string |
| **_script_decision_node** | `app.agents.supervisor` | LLM 决策是否需要脚本 | `{need_script, phase}` |
| **_script_designer_node** | `app.agents.supervisor` | 结构化输出 SceneScript JSON | `{current_script, phase: "scripting"}` |
| **_make_coder_node** | `app.agents.supervisor` | `create_agent` + 4 层兜底（invoke_with_recovery） | `{code, thought, scene_name, code_round}` |
| **_reviewer_node** | `app.agents.supervisor` | `build_reviewer_llm` + `with_structured_output(CodeReview)` | `{review, previous_feedback?}` |
| **_route_after_reviewer** | `app.agents.supervisor` | 决定 reviewer 后去向 | string only（不能 dict） |

### 文件依赖（单向）

```
api/v1/conversations.py      ← HTTP 入口（不接触 LangGraph 内部）
  ↓
agents/service.py            ← 唯一编排入口（run_initial / run_after_confirm / run_refine）
  ↓
agents/supervisor.py         ← build_supervisor 工厂（StateGraph 装配）
  ↓
agents/script_designer.py    ← SceneScript + 提示词
agents/reviewer.py           ← build_reviewer_llm + CodeReview schema
agents/builder.py            ← create_agent 工厂（Coder 内部用）
agents/agent_recovery.py     ← invoke_with_recovery 4 层兜底
agents/middleware/persistence.py  ← AgentPersistenceMiddleware（自动落 agent_steps）
  ↓
agents/dao/                  ← 单表 CRUD（每个表一个文件）
  ↓
db/session.py + db/models/
```

**6 层分工**：
1. **`agents/dao/`** — 单表数据访问
2. **`agents/middleware/`** — 业务中转，调 DAO
3. **`agents/agent_recovery.py`** — 错误兜底
4. **`agents/builder.py` + `supervisor.py` + `reviewer.py` + `script_designer.py`** — Agent 节点装配
5. **`agents/service.py`** — 业务编排入口
6. **`api/v1/`** — HTTP 层

---

## 🤖 Coder Agent：`create_agent` 产物

### Agent 签名

```python
# app/agents/builder.py
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from app.agents.schemas import CodeOutput
from app.agents.tools import validate_manim_code, render_manim_dryrun

@lru_cache
def build_agent(style_id: str, extra_system_prompt: str = ""):
    llm: ChatOpenAI = get_llm()
    return create_agent(
        model=llm,
        tools=[validate_manim_code, render_manim_dryrun],
        system_prompt=compose(style_id, extra_system_prompt),
        response_format=CodeOutput,
    )
```

### 业务入口（v1.0 当前）

```python
# app/agents/service.py
class AgentService:
    async def _run_agent(self, *, style, few_shots, on_event, prompt_text,
                         user_id, conversation_id, label, phase):
        memory_block = await build_memory_block(self.session, user_id=user_id)
        middleware = AgentPersistenceMiddleware(
            dao_steps=self.dao_steps, dao_messages=self.dao_msg,
        )
        supervisor = build_supervisor(
            style_id=style,
            extra_system_prompt=memory_block,
            few_shots=list(few_shots),
            middleware=[middleware],
            phase=phase,  # ⭐ scripting / coding — 决定 entry_router
        )
        supervisor_input = {
            "messages": [HumanMessage(content=prompt_text)],
            "conversation_id": conversation_id,
            "on_event": on_event,
            "code_round": 0,
        }
        final_state = await invoke_with_recovery(
            supervisor, supervisor_input, ...
        )
        return final_state["assistant_message"], final_state
```

### 工具列表

| 工具 | 实现 | 状态 |
|---|---|---|
| `validate_manim_code(code)` | [`backend/app/agents/tools.py`](../../backend/app/agents/tools.py) | ✅ |
| `render_manim_dryrun(code)` | [`backend/app/agents/tools.py`](../../backend/app/agents/tools.py) | ✅ |
| Validator 底层 | [`backend/app/tools/validator.py`](../../backend/app/tools/validator.py) | ✅ |
| Renderer 底层 | [`backend/app/renderers/manim.py`](../../backend/app/renderers/manim.py) | ✅ |

---

## 💾 长期记忆（v1.0 P3 新增）

### 三类记忆

| 来源 | 字段 | 用途 |
|---|---|---|
| `user_preferences` | `default_style, language, preferred_scene_count, ...` | 创建会话时塞 system prompt 头部 |
| `user_algorithm_history` | `user_id, algorithm, last_used_at, use_count` | 避免重复推荐 + 序列学习 |
| `user_memories` | `user_id, kind, content, importance, source_conversation_id` | Memory Curator 提取的语义记忆 |

### Memory Curator

每条 conversation 跑完后异步调 `MemoryCurator.analyze_run()`：
- 输入：本轮 `prompt / code / status / error / feedback`
- 输出：0-N 条 `MemoryEvent(kind, content, importance)`
- 存储：批量写 `user_memories`，跨会话可读

### 召回（`build_memory_block`）

```python
async def build_memory_block(session, user_id) -> str:
    prefs = await user_preferences_dao.get(user_id)
    algos = await user_algo_history_dao.recent(user_id, limit=5)
    memories = await user_memories_dao.top_k(user_id, k=10)
    return compose_memory_block(prefs, algos, memories)
```

拼到 system prompt 头部，Coder / Reviewer / Script Designer 都能看到。

---

## 📊 端到端数据流（v1.0 当前）

### 首次生成（含 Script Designer 分诊）

```
[1] 前端 POST /api/v1/conversations (SSE)
   ↓
[2] FastAPI 路由
   ├─ few-shot 召回
   ├─ 长期记忆块拼装
   └─ AgentService.run_initial(phase=scripting)
       ↓
[3] AgentPersistenceMiddleware.before_agent
   └─ 建 assistant 消息壳（status=generating）
       ↓
[4] Supervisor.ainvoke
   ├─ entry_router → script_decision
   ├─ script_decision (LLM 决策 need_script)
   │   ├─ need_script=true → script_designer
   │   │   └─ SceneScript JSON → __end__（等用户确认）
   │   └─ need_script=false → coder
   │       └─ coder → reviewer → (feedback) → coder ... → __end__
   └─ 中间件 after_agent 收尾
       ↓
[5] FastAPI
   ├─ phase=scripting → SSE 推 script_ready + done（前端弹脚本面板）
   └─ phase=coding → 渲染 → SSE 推 done
       ↓
[6] 后台异步（不阻塞响应）
   └─ MemoryCurator.analyze_run → 写 user_memories
```

### 脚本确认（confirm）

```
[1] 前端 POST /api/v1/conversations/{id}/confirm（用户点确认）
   ↓
[2] FastAPI confirm_conversation
   ├─ 校验 conv.phase == "scripting"
   ├─ set_phase(coding)
   ├─ AgentService.run_after_confirm(phase=coding)
   │   └─ Supervisor.ainvoke(phase=coding)
   │       └─ entry_router → coder（直接跳过 script_decision / designer）
   │           └─ coder ↔ reviewer 循环
   ├─ render_code → to_video_url
   ├─ attach_video
   └─ 响应 {code, scene_name, video_url, duration_sec}
```

### 多轮调整（refine）

```
[1] 前端 POST /api/v1/conversations/{id}/refine (SSE)
   ↓
[2] FastAPI
   ├─ 追加 user message
   ├─ AgentService.run_refine
   │   ├─ _build_refine_prompt([历史 user 指令 cap 6] + [上一版代码] + [本次 user 调整])
   │   └─ Supervisor.ainvoke(phase=coding)
   │       └─ coder ↔ reviewer
   └─ 渲染 → SSE 推 done
```

---

## 🧪 可测试性（v1.0 当前）

`backend/tests/agents/` **20+ 用例覆盖**：

| 测试文件 | 验证什么 |
|---|---|
| `test_supervisor.py`（21 用例） | Supervisor 节点 / 条件边 / router 必须只返 string / Reviewer 失败时 previous_feedback 写到 state |
| `test_service_run_initial.py`（6 用例） | run_initial 默认 phase=scripting / scripting 阶段不要求 assistant_msg / coding 阶段必走 Coder / run_after_confirm 透传 phase |
| `test_script_designer.py` | SceneScript schema + 提示词拼装 |
| `test_memory.py` | build_memory_block 在空数据 / 满数据下拼装正确 |
| `test_memory_curator.py` | MemoryCurator 解析 + 落 user_memories |
| `test_recovery_fallback.py` | 4 层兜底（thinking / 字符串扫描 / 代码栅栏 + 1-shot retry） |
| `test_retriever.py` | few-shot 召回（embedding 命中 / fallback recency） |
| `test_coder.py` | Coder agent 端到端结构化输出 |

测试用 `unittest.mock` patch LLM / DB / middleware，**无 LLM 网络调用、无 manim subprocess**。

---

## 🔁 跟 v1.0 早期的对比

| 维度 | v1.0 早期 | v1.0 当前（P2/P3） |
|---|---|---|
| Agent 数 | 1（Coder） | 3（Script Designer + Coder + Reviewer）+ Supervisor 编排 |
| 编排 | 单 `create_agent` | LangGraph `StateGraph` Supervisor + 条件边 |
| 入口分诊 | 无（直接 Coder） | LLM 决策 need_script |
| 脚本确认 | 无 | Script Designer 出 JSON → 用户确认 → confirm 续跑 |
| Reviewer | 无 | 独立节点，CodeReview 结构化输出 |
| 持久化 | 路由层手写埋点 | LangChain `AgentMiddleware` 统一入口 |
| 长期记忆 | 无 | user_preferences + user_algorithm_history + user_memories + Memory Curator |
| 业务代码位置 | `api/v1/generate.py` 直接调 `run_agent` | `api/v1/conversations.py` → `AgentService` → `build_supervisor` |
| 可视化 | 无 | `g.draw_mermaid()` 出图 |
| 测试用例 | 107 | 186+ |

---

## 🚀 演进路径

| 版本 | 工作流 | Agent 数 | 备注 |
|---|---|---|---|
| v1.0 早期 | `create_agent` + response_format | 1 | 单 agent 直跑 |
| **v1.0 当前** | StateGraph Supervisor | 3 + middleware | 入口分诊 + 脚本 + Coder↔Reviewer + 长期记忆 |
| v1.x | + Worker 异步化（rq.enqueue） | 同上 | 解 API 阻塞 |
| v1.x | + 真 Supervisor（subgraph）评估 | 3+ | 等 greenlet BUG 修了再上 |
| v2.0 | + 多用户多轮（编辑模式 + diff） | 3+ | 编辑器 + 选择性重新渲染 |
| v2.x | + 工具扩展（视觉校验 / 自动调色） | 3+ | 加 @tool 即可 |

---

## ❓ 待回答 / 待办

- [ ] Worker 异步化（v1.x 最高优先）
- [ ] 补 few-shot 库（v1.0 要 3 个，目前只有用户自积累）
- [ ] Script Designer prompt 调优（复杂 prompt 准确率↑）
- [ ] Reviewer 是否值得长期开（每次 +1 次 LLM 调用）
- [ ] 真 Supervisor（subgraph）能否修 greenlet 问题

---

## 🔗 相关文档

- Agent 代码 → [`backend/app/agents/`](../../backend/app/agents/)
- 模型适配层 → [`backend/app/llm/client.py`](../../backend/app/llm/client.py)
- 系统架构 → [docs/architecture.md](architecture.md)
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 范围与里程碑 → [docs/mvp-scope.md](mvp-scope.md)
