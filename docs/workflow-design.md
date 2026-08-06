# 05 · 工作流与 Agent 设计

> 反映 v1.0 **实际状态**。原 v0.1 LangGraph 状态机设计未落地，保留作为未来迁移蓝图。
>
> 实际在用的代码：[backend/app/agents/coder/](backend/app/agents/coder/)（手写 loop + LangChain 零件）
> 死代码：[backend/app/agents/react_coder.py](backend/app/agents/react_coder.py)（LangGraph ReAct，MiniMax 不支持 tool_calls）

---

## 🎯 设计目标（保留）

1. **流程可控**：每一步出错都能定位、能修
2. **可扩展**：v0.2+ 加新 Agent / 渲染器不破坏现有代码
3. **可调试**：能看每一步的输入输出、LLM 实际调用
4. **可重试**：错误能自动恢复，不是一次失败就完蛋

---

## 🧠 选型结论（v1.0 实际）

| 候选 | 决策 | 原因 |
|---|---|---|
| **手写 agent loop + LangChain 零件** ✅ | **当前在用** | MiniMax 不支持 tool_calls，被迫手写；用 LangChain 的 `ChatOpenAI` / `PydanticOutputParser` / `StrOutputParser` / `RunnableSequence` 减负 |
| **LangGraph StateGraph** ⏸️ | 蓝图保留 | 等换支持 tool_calls 的 LLM 后可平滑迁移 |
| 自研状态机 | ✗ | 多 1000+ 行样板 |
| Temporal | ✗ | 太重 |

---

## 🔄 实际工作流（手写 loop）

### 单轮流程

```
[1] 收 prompt
    ↓
[2] build_chain (RunnableSequence)
    ChatPromptTemplate → ChatOpenAI → StrOutputParser → PydanticOutputParser(CodeOutput)
    ↓
[3] chain.ainvoke({prompt, few_shot})
    ↓
[4] validate_only_retry (max 2 次)
    ├─ AST 校验
    ├─ 危险模式黑名单
    ├─ Scene 子类 + construct() 检查
    └─ 失败 → 把 stderr 回喂 LLM 重试
    ↓
[5] render_manim_subprocess (timeout=60s)
    ├─ 写 tmp/{task_id}.py
    ├─ subprocess.run(['manim', ...])
    └─ 落 media/{task_id}.mp4
    ↓
[6] SSE 推 done
```

### 文件依赖（单向）

```
coder.py / sync.py / stream.py   ← 入口（CoderAgent 类、run_sync、run_streaming）
  ↓
retry.py                         ← load_system_prompt + build_user_message + validate_only_retry + call_llm_once
  ↓
chain.py + parser.py             ← PROMPT_TEMPLATE + RunnableSequence + CodeOutput 解析
  ↓
langchain SDK                    ← ChatOpenAI / PydanticOutputParser / StrOutputParser
```

---

## 🤖 实际 Agent：CoderAgent

### 职责
**单一职责**：给定 prompt → 输出可执行 Manim 代码（含渲染）。

### 类签名（[backend/app/agents/coder/coder.py](../../backend/app/agents/coder/coder.py)）

```python
class CoderAgent:
    def __init__(self, llm, prompt_loader):
        ...

    async def run(
        self,
        prompt: str,
        prev_error: Optional[str] = None,
    ) -> AgentResult:
        """同步入口：返回 {code, steps, attempts}"""

    async def run_streaming(
        self,
        prompt: str,
    ) -> AsyncIterator[AgentStep]:
        """SSE 流式入口：yield {stage, attempt, code, error}"""
```

`AgentStep.stage ∈ {"coding", "validating", "rendering", "rendered", "done", "failed"}`

---

## 🛠 Tool 抽象（实际状态）

### 当前 Tools

| Tool | 实现位置 | 状态 |
|---|---|---|
| **Validator**（AST + 黑名单 + Scene 检查） | [backend/app/tools/validator.py](../../backend/app/tools/validator.py) | ✅ 直接调函数，不走 `@tool` 装饰 |
| **Renderer**（subprocess + 60s） | [backend/app/renderers/manim.py](../../backend/app/renderers/manim.py) | ✅ 同上 |
| `@tool` 装饰的 validate_manim_code / render_manim_dryrun | [backend/app/agents/tools.py](../../backend/app/agents/tools.py) | ⚠️ **死代码**（MiniMax 不支持 tool_calls） |

### 抽象接口（预留）

```python
# renderers/base.py
class BaseRenderer(ABC):
    @abstractmethod
    async def render(self, code: str, options: dict) -> RenderResult: ...
```

未来加 `renderers/svg.py` / `renderers/remotion.py` 时不破现状。

---

## 📊 端到端数据流（实际）

```
[1] 前端 POST /api/v1/render { prompt, quality }
    ↓
[2] FastAPI 同步执行
    ├─ CoderAgent.run_streaming(prompt)
    │   ├─ chain.ainvoke → CodeOutput JSON
    │   ├─ validate_only_retry（最多 N 次，错误回喂）
    │   ├─ SSE: {stage: "validated"}
    │   ├─ 写 tmp/{task_id}.py
    │   ├─ subprocess.run(['manim', ...], timeout=60)
    │   ├─ SSE: {stage: "rendered"}
    │   └─ SSE: {stage: "done", video_url: "/media/{task_id}.mp4"}
    └─ 返回 RenderResponse
    ↓
[3] 前端 EventSource 收 done → 渲染 <video>
```

---

## 🧪 可测试性（实际）

```python
# tests/agents/test_coder.py（4/4 通过）
- test_agent_returns_code_on_first_try
- test_agent_retries_when_render_fails
- test_agent_returns_none_when_validation_keeps_failing
- test_agent_handles_llm_call_failure
```

测试 helper 用真 `AIMessage`（**不能**用 MagicMock，跟 `StrOutputParser.parse()` 的 Pydantic 校验不兼容）。

---

## 🚀 演进路径

| 版本 | 工作流 | Agent 数 | LLM | 备注 |
|---|---|---|---|---|
| **v1.0 当前** | 手写 loop | 1 (Coder) | MiniMax-M3 | 同步渲染、阻塞 API |
| **v1.0 TODO** | + Worker 异步化 | 1 + rq worker | MiniMax-M3 | 解 API 阻塞 |
| **v1.x** | + Reviewer 节点 / Self-Reflection | 2+ | 同上 | 提升代码正确率 |
| **v2.0** | + LangGraph StateGraph | 3+ | 切支持 tool_calls 的 LLM | 重构成状态机 |
| **v2.x** | + 多轮交互（用户迭代修改） | 4+ | 同上 | 编辑器 + 重新渲染 |

---

## ❓ 待回答 / 待办

- [ ] Worker 异步化（最高优先）
- [ ] 补 few-shot 库（v1.0 要 3 个，目前 1 个）
- [ ] 清理死代码（`react_coder.py` / `tools.py` / `/generate` / `/generate/agent`）
- [ ] LLM 输出格式：当前 JSON `{thought, code}`，是否值得换纯文本 + 注释结构？
- [ ] Fixer Agent 独立还是 Coder 加个"fix mode"？（当前是后者）
- [ ] 任务状态要不要持久化到 Postgres？（v1.x 决策）

---

## 🔗 相关文档

- 实际 Agent 代码 → [backend/app/agents/coder/](../../backend/app/agents/coder/)
- LLM Prompt → [docs/llm-prompt.md](llm-prompt.md)
- 本次 session 改动 → [docs/session-summary.md](session-summary.md)
- 系统架构 → [docs/architecture.md](architecture.md)
