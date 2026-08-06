# 05 · 工作流与 Agent 设计

> 反映 v1.0 **实际状态**（2026-08 更新）。
>
> 本次大改动：从"手写 agent loop + LangChain 零件"迁移到**标准 LangChain 1.x `create_agent` + `.with_structured_output()` + LiteLLM 适配层**。手写 LCEL chain / 手写工具循环 / 手写 JSON 解析全部删除。详见 [docs/session-summary.md](session-summary.md)。

---

## 🎯 设计目标

1. **流程可控**：每一步出错都能定位、能修
2. **可扩展**：v0.2+ 加新 Agent / 渲染器不破坏现有代码
3. **可调试**：能看每一步的输入输出、LLM 实际调用
4. **可重试**：错误能自动恢复，不是一次失败就完蛋
5. **厂商中立**：业务代码不绑死 MiniMax，换模型只改 `app/llm/client.py` 一个文件

---

## 🧠 选型结论（v1.0 当前）

| 候选 | 决策 | 原因 |
|---|---|---|
| **langchain-litellm 适配层 + 标准 `create_agent`** ✅ | **当前在用** | LiteLLM 内部归一化 MiniMax 的 tool/think 协议；业务层只见 `ChatOpenAI`；换厂商只改 `client.py` |
| 手写 agent loop + LangChain 零件 | ❌ 已废弃 | 维护成本高；JSON 解析、工具循环、LCEL 装配全是样板 |
| LangGraph `create_react_agent`（旧版本） | ❌ 已废弃 | 是 1.x 之前的状态机封装，不是 LangChain 标准 |
| 自研状态机 | ✗ | 多 1000+ 行样板 |
| LiteLLM proxy 独立服务 | ✗ | 违背"不启 proxy 服务"开局约束 |

### 为什么是 langchain-litellm 而不是 ChatOpenAI 直连

- **MiniMax 不直接兼容 OpenAI 协议**：tool_call 字段格式 + 私有 `<think>` 通道会让标准 `ChatOpenAI` 拿到空 `tool_calls`
- **litellm 内嵌调用**（不启 proxy）通过 `langchain-litellm.ChatLiteLLM` 在库内做协议归一化，对业务透明
- 业务代码导入 `langchain_openai.ChatOpenAI`，运行时实际是 `ChatLiteLLM`——类型契约一致，运行行为兼容

---

## 🔄 实际工作流（标准 `create_agent`）

### 单轮流程

```
[1] 收 prompt (HTTP)
    ↓
[2] app.api.v1.generate 路由处理
    ↓
[3] app.agents.react_coder.run_agent(prompt, max_iterations)
    ↓
[4] app.agents.builder.build_agent() → CompiledStateGraph (单例，lru_cache)
    │   create_agent(
    │       model=llm,                  ← ChatOpenAI 类型，运行时 ChatLiteLLM
    │       tools=TOOLS,                ← [validate_manim_code, render_manim_dryrun]
    │       system_prompt=SYSTEM_PROMPT,
    │       response_format=CodeOutput, ← Pydantic 结构化输出 schema
    │   )
    ↓
[5] agent.ainvoke({"messages": [HumanMessage(prompt)]})
    │   LangGraph 内置工具循环：
    │   ├─ LLM 生成代码 / 调用工具
    │   ├─ validate_manim_code → "OK" / "errors: ..."
    │   ├─ render_manim_dryrun → "rendered ok: ..." / "render error: ..."
    │   ├─ 报错 → 改代码 → 再 validate → 再 render
    │   └─ 收敛 → 产出 CodeOutput{thought, code}
    ↓
[6] result["structured_response"] → run_agent 抽 {code, tool_log, messages}
    ↓
[7] HTTP 端点包装 + SSE 推 done / failed
```

### 文件依赖（单向）

```
api/v1/generate.py          ← HTTP 入口（不接触 LangChain 内部）
  ↓
agents/react_coder.py       ← 业务入口 run_agent() + 日志
  ↓
agents/builder.py           ← 唯一调用 create_agent 的地方 + TOOLS / SYSTEM_PROMPT
  ↓
agents/tools.py             ← @tool 装饰的工具函数
agents/state.py             ← Pydantic CodeOutput（response_format schema）
  ↓
llm/client.py               ← 唯一出现 ChatLiteLLM 的地方；业务只见 ChatOpenAI
  ↓
config.py                   ← LLM_* 配置 + .env 加载
```

**4 层分工**：
1. **`state.py`** — 数据契约（agent 返回什么形状）
2. **`tools.py`** — 能力单元（agent 能调什么）
3. **`builder.py`** — 装配工厂（怎么把上面组装成 agent）
4. **`react_coder.py`** — 调用入口（业务方怎么调）

---

## 🤖 标准 Agent：`create_agent` 产物

### Agent 签名

```python
# app/agents/builder.py
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from app.agents.state import CodeOutput
from app.agents.tools import validate_manim_code, render_manim_dryrun

@lru_cache
def build_agent():
    llm: ChatOpenAI = get_llm()  # 静态类型 ChatOpenAI，运行时 ChatLiteLLM
    return create_agent(
        model=llm,
        tools=[validate_manim_code, render_manim_dryrun],
        system_prompt=SYSTEM_PROMPT,
        response_format=CodeOutput,
    )
# → CompiledStateGraph
```

### 业务入口

```python
# app/agents/react_coder.py
async def run_agent(prompt: str, *, max_iterations: int = 6) -> dict:
    agent = build_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"recursion_limit": max_iterations * 4 + 1},
    )
    structured = result["structured_response"]    # CodeOutput 实例
    return {
        "code": structured.code if structured else None,
        "tool_log": [...],
        "messages": [...],
    }
```

---

## 🛠 Tool 抽象

### 当前 Tools（标准 `@tool` 装饰器）

| Tool | 实现位置 | 状态 |
|---|---|---|
| `validate_manim_code(code)` | [backend/app/agents/tools.py](../../backend/app/agents/tools.py) | ✅ agent 直接调用 |
| `render_manim_dryrun(code)` | [backend/app/agents/tools.py](../../backend/app/agents/tools.py) | ✅ agent 直接调用 |
| Validator 底层 (`validate_code`) | [backend/app/tools/validator.py](../../backend/app/tools/validator.py) | ✅ 纯函数，tool 调用它 |
| Renderer 底层 (`render_code`) | [backend/app/renderers/manim.py](../../backend/app/renderers/manim.py) | ✅ 纯函数，tool 调用它 |

新增工具只需在 `tools.py` 加一个 `@tool` 函数，在 `builder.py::TOOLS` 列表注册，零改动其他文件。

---

## 📊 端到端数据流（实际）

```
[1] 前端 GET /api/v1/generate/stream?prompt=...  (SSE)
    ↓
[2] FastAPI 路由处理
    ↓
[3] react_coder.run_agent(prompt, max_iterations=8)
    ├─ 日志：agent.run start
    ├─ agent.ainvoke
    │   ├─ LLM 生成代码
    │   ├─ 调用 validate_manim_code（AST + 黑名单 + Scene 检查）
    │   ├─ 调用 render_manim_dryrun（subprocess + 60s）
    │   ├─ 报错 → 改 → 再调
    │   └─ 收敛 → structured_response = CodeOutput(thought, code)
    └─ 日志：agent.run end
    ↓
[4] 抽 code → render_code() → media/{task_id}.mp4
    ↓
[5] SSE 推 events：
    ├─ event: started {prompt}
    ├─ event: code {code, scene_name}
    ├─ event: rendering {scene_name}
    └─ event: done {code, video_url, duration_sec}
       或 event: failed {error, tool_calls, iterations, last_message}
    ↓
[6] 前端 EventSource 收 done → 渲染 <video>
```

---

## 🧪 可测试性（实际）

`backend/tests/agents/test_coder.py` **6/6 通过**：

| 测试 | 验证什么 |
|---|---|
| `test_get_llm_is_typed_as_chat_openai` | `get_llm()` 静态返回类型注解是 `ChatOpenAI`（即业务层只见 `ChatOpenAI`）|
| `test_code_output_schema_validates_and_normalises` | `CodeOutput` 自动截掉 `from manim import` 之前的废话 |
| `test_code_output_passes_through_when_already_clean` | 已干净的代码原样保留 |
| `test_build_agent_uses_create_agent_standard_api` | `create_agent` 用 `model=` + `tools=` + `system_prompt=` + `response_format=` 标准四参数调用 |
| `test_tools_are_standard_langchain_tools` | 两个工具都是 `@tool` 装饰 |
| `test_run_agent_returns_structured_code` | `run_agent` 端到端抽 `structured_response.code` |

测试用 `unittest.mock` patch `ChatLiteLLM` 和 `create_agent`，**无 LLM 网络调用、无 manim subprocess**。

---

## 🔁 跟前一版的对比

| 维度 | 旧版（手写 loop） | 新版（标准 create_agent） |
|---|---|---|
| Agent 文件数 | 6 个（coder/parser.py, chain.py, retry.py, coder.py, sync.py, stream.py）+ react_coder.py | 4 个（state.py, tools.py, builder.py, react_coder.py） |
| 总行数 | ~530 行 | ~250 行（-53%）|
| 结构化输出 | `PydanticOutputParser` + 手写 fallback | `llm.with_structured_output()` 或 `response_format=` 参数 |
| 工具循环 | 手写 `for step in range(max_steps)` + try/except | LangGraph 内置 |
| JSON 解析失败 | `parse_with_fallback` + `_extract_code_from_import` | Pydantic 自动校验，LangChain 处理 |
| Think 块剥离 | 手写 `_THINK_BLOCK` 正则 | LiteLLM 库内吸收，业务层无感 |
| 模型层 | `langchain_openai.ChatOpenAI` 直连 MiniMax | `langchain_litellm.ChatLiteLLM` 封装为 `ChatOpenAI`（type cast） |
| 厂商切换 | 改 `base_url` + 多处适配 | 改 `client.py` 一个文件 |

---

## 🚀 演进路径

| 版本 | 工作流 | Agent 数 | LLM | 备注 |
|---|---|---|---|---|
| **v1.0 当前** | 标准 `create_agent` + `response_format` | 1 (Coder) | MiniMax-M3 (via LiteLLM) | 同步渲染、阻塞 API |
| **v1.0 TODO** | + Worker 异步化 | 1 + rq worker | 同上 | 解 API 阻塞 |
| **v1.x** | + Reviewer 节点 / Self-Reflection | 2+ | 同上 | 提升代码正确率 |
| **v2.0** | + 多 Agent 编排（orchestrator） | 3+ | 切支持 tool_calls 的原生 OpenAI / DeepSeek | 加 Plan-Execute 分离 |
| **v2.x** | + 多轮交互（用户迭代修改） | 4+ | 同上 | 编辑器 + 重新渲染 |

---

## ❓ 待回答 / 待办

- [ ] Worker 异步化（最高优先）
- [ ] 补 few-shot 库（v1.0 要 3 个，目前 1 个）
- [ ] LiteLLM 链路偶发 Connection error 的兜底重试
- [ ] LLM 输出格式：当前 `CodeOutput{thought, code}` 是否需要扩字段（如 `confidence`、`scene_name`）？
- [ ] 任务状态持久化到 Postgres？（v1.x 决策）
- [ ] Step 5 完整实施（user/history 表 + 中英切换 + LangSmith 替代品）

---

## 🔗 相关文档

- Agent 代码 → [backend/app/agents/](../../backend/app/agents/)
- 模型适配层 → [backend/app/llm/client.py](../../backend/app/llm/client.py)
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 系统架构 → [docs/architecture.md](architecture.md)
