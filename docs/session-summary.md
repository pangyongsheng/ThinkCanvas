# Session 工作总结

## 项目背景
ThinkCanvas：文字描述 → LLM 生成 Manim 代码 → 渲染成算法/数学动画视频。
- 后端：FastAPI + langchain-openai（MiniMax OpenAI 兼容 API）
- 前端：Next.js 15

## 核心约束
**MiniMax 不支持 `tool_calls`** → 不能用 `create_agent` / `bind_tools` 这类 LangChain 原生 agent 范式 → 必须手写 agent loop。

## 本次 session 完成的工作

### 1. LangChain 化 LLM 调用（替换手写实现）
- 引入 `CodeOutput` Pydantic 模型 + `PydanticOutputParser`（替掉手写 JSON 解析）
- 用 `ChatPromptTemplate` 模板化 prompt（替掉 `.txt` 文件 + 手动拼接）
- 用 `StrOutputParser` 提取 content（替掉手写 RunnableLambda）
- LCEL 用 `RunnableSequence` 构造器（不用 `|`，避免静态类型报错）
- 简化 fallback：`code_parser.parse() → 失败 → _extract_code_from_import()`

### 2. 文件结构规范化
原来：所有 agent 代码塞在 `coder.py`（388 行）  
现在：

```
backend/app/agents/
├── __init__.py
├── react_coder.py        # 死代码：LangGraph ReAct agent（MiniMax 不支持 tool_calls）
├── tools.py              # 死代码：@tool 装饰的 validate_manim_code / render_manim_dryrun
└── coder/
    ├── __init__.py
    ├── parser.py   66 行  # CodeOutput + parse_with_fallback + strip_think_blocks
    ├── chain.py    46 行  # PROMPT_TEMPLATE + build_chain (RunnableSequence)
    ├── retry.py    89 行  # load_system_prompt + build_user_message + validate_only_retry + call_llm_once
    ├── coder.py   154 行  # CoderAgent 类 + AgentStep + AgentResult
    ├── sync.py     39 行  # run_sync + GenerateOutcome（一次性返回）
    └── stream.py   45 行  # run_streaming（SSE 流式）
```

依赖方向（单向）：
```
coder.py / sync.py / stream.py
  ↓ retry.py
  ↓
chain.py + parser.py
  ↓
langchain SDK
```

### 3. HTTP 层精简（generate.py）
之前 generate.py 直接 `get_llm()` + 自己写 retry 循环  
现在 generate.py 只做：收请求 → 调 agent 入口 → 包响应。

`generate.py` 现在 3 个 endpoint：
- `POST /generate`（legacy，validate-only，无渲染）—— 前端不用
- `POST /generate/agent`（LangGraph ReAct，跑不通）—— 死代码
- `GET /generate/stream`（**生产用**，SSE + 渲染）

### 4. 测试
`backend/tests/agents/test_coder.py` 4/4 通过：
- `test_agent_returns_code_on_first_try`
- `test_agent_retries_when_render_fails`
- `test_agent_returns_none_when_validation_keeps_failing`
- `test_agent_handles_llm_call_failure`

测试 helper 改用真 `AIMessage`（之前用 MagicMock，跟 `StrOutputParser` 不兼容）。

### 5. Docstring 全部中文
6 个 agent 文件的 docstring 都改成中文。

## 当前状态

### 项目能跑的部分
- ✅ `langchain-openai` + MiniMax OpenAI 兼容 API 接通
- ✅ 调 LLM 出 Manim 代码（结构化 JSON 输出 + Pydantic 解析）
- ✅ 校验重试（`validate_only_retry`）
- ✅ Manim 渲染（subprocess + 60s timeout）
- ✅ SSE 流式推送进度
- ✅ 4/4 测试通过

### 项目没跑通的部分（已知）
- ❌ `react_coder.py` 的 LangGraph ReAct agent——MiniMax 不支持 tool_calls
- ❌ `bind_tools` / `create_agent` 直接用 MiniMax——同上
- ❌ LiteLLM proxy 方案——**本次 session 试图引入但安装链太长放弃**

## 关键技术决策（交接必读）

### 1. 为什么不用 `create_agent` / `bind_tools`
MiniMax 不支持 OpenAI 风格的 `tool_calls`。  
验证过：
- `langchain_community.chat_models.MiniMaxChat` 存在但包被废弃
- 没有 `langchain-minimax` 官方包
- LiteLLM proxy 起不来（缺太多依赖：boto3 / prisma / pyjwt 等 10+ 个）

**结论**：维持手写 agent loop。用 LangChain 的零件（parser / LCEL）但不用 agent 大脑。

### 2. chain 用 `RunnableSequence` 构造器，不用 `|`
LangChain 的 `|` 类型签名静态分析推断不通。  
用 `RunnableSequence(first=..., middle=[...], last=...)` 显式构造，类型干净。

### 3. 测试用 `AIMessage`，不用 MagicMock
`StrOutputParser.parse()` 内部用 `Generation(text=...)` Pydantic 校验，会拒绝 MagicMock。  
测试 helper 必须返 `AIMessage`。

### 4. agent loop 的 try/except 包 chain.ainvoke
网络错误就跳过这一步 + 记 `LLM call failed`。  
没用 `chain.with_retry()`，因为我们的 retry 是给校验失败用的，不是网络错误。

## 下一步建议（待接手）

按优先级：

1. **重跑 e2e**：手动从前端触发一次生成，确认 SSE + 渲染链路通
2. **补 few-shot**：v1.0 要求 3 个算法，目前只有 1 个（冒泡排序）。补 二分查找 + 图 BFS
3. **清理死代码**：考虑删 `react_coder.py` + `tools.py` + `/generate` + `/generate/agent`
4. **持久化**：Step 5（user 表 + history 表 + 中英切换）
5. **端到端压测**：Step 6（3 算法 × 10 次）

## 已知风险

- MiniMax 不稳定：复杂 prompt（few-shot 长了）可能超时
- `manim_timeout=60s`：复杂动画可能不够
- LaTeX 没装：`MathTex` 会报错，但 prompt 已经禁用

## 相关文档

- `docs/mvp-scope.md`：项目范围 + 6 步开发步骤
- `docs/product.md`：产品定位
- `docs/tech-stack.md`：技术栈选型
- `shared/prompts/system/v1.txt`：当前 prompt（只有冒泡排序 1 个 few-shot）
---

## Session #2: LiteLLM 适配层 + 标准 LangChain 1.x 重构（2026-08-06）

### 背景
Session #1 留的现状是手写 agent loop + LangChain 零件。问题：
1. MiniMax 不支持 OpenAI 标准 `tool_calls`，被迫手写解析循环
2. JSON 输出走 `PydanticOutputParser` + 手写 fallback regex
3. `<think>` 块要手写正则剥
4. Agent 文件 6 个，加 react_coder.py 一共 7 个，~530 行手写样板

### 目标
业务代码全部用 LangChain 1.x 标准写法（`create_agent` / `with_structured_output` / `ChatOpenAI`），靠 LiteLLM 抹平 MiniMax 协议差异。

### 关键决策
**A. 模型层用 `langchain_litellm.ChatLiteLLM`，对外暴露为 `ChatOpenAI` 类型**

理由：
- 业务代码 100% 标准 LangChain 写法（`from langchain_openai import ChatOpenAI`）
- LiteLLM 内嵌调用（不启 proxy 服务），守住开局约束
- 运行时是 `ChatLiteLLM` 实例，静态类型注解是 `ChatOpenAI`，用 `cast()` 桥接
- 切换厂商（DeepSeek / OpenAI 原生）只改 `client.py` 一个文件

**B. 结构化输出用 `create_agent(..., response_format=CodeOutput)`**

不是 `llm.with_structured_output(CodeOutput)` —— 因为后者返回 `RunnableSequence`，不是 `BaseChatModel`，`create_agent.model=` 参数不接受。LangChain 1.x 标准做法是 `model` + `response_format` 分开传。

**C. 删除所有手写循环、解析、chain 装配**

- `coder/parser.py` —— 删除（被 Pydantic 自动校验取代）
- `coder/chain.py` —— 删除（LCEL 装配被 `create_agent` 内置取代）
- `coder/coder.py` —— 删除 `CoderAgent` 手写循环
- `coder/retry.py` —— 删除 `validate_only_retry`（agent 内置工具循环）
- `coder/sync.py` —— 删除（重写 `run_agent` 一处）
- `coder/stream.py` —— 删除（SSE 在 HTTP 层重写）

### 最终结构

```
backend/app/
├── llm/
│   └── client.py          # 唯一出现 ChatLiteLLM；cast(ChatOpenAI, litellm_chat)
├── agents/
│   ├── state.py           # Pydantic CodeOutput（response_format schema）
│   ├── tools.py           # @tool 装饰的工具函数
│   ├── builder.py         # create_agent(model=, tools=, system_prompt=, response_format=)
│   └── react_coder.py     # run_agent 入口 + 日志
├── core/
│   └── logging.py         # structlog + 全局异常中间件（可观测性）
├── api/v1/generate.py     # 3 个端点（/generate、/generate/agent、/generate/stream）
└── main.py                # load_dotenv + configure_logging + FastAPI 工厂
```

### 验证结果

| 检查 | 结果 |
|---|---|
| `pytest tests/agents/test_coder.py` | **6/6 通过** |
| 静态扫描：业务层 0 个 `ChatLiteLLM` 引用 | ✅ |
| 静态扫描：可执行代码 0 个 `ChatOpenAI` / `MiniMaxChat` / `langchain_community` / `strip_think_blocks` | ✅ |
| `get_llm()` 静态类型注解 = `ChatOpenAI` | ✅ |
| `get_llm()` 运行时类型 = `ChatLiteLLM` | ✅ |
| `create_agent(...)` 产出 `CompiledStateGraph` | ✅ |
| 前端实测（"画一个旋转的正方形"）出 mp4 | ✅ |

### 踩坑记录

1. **`langchain-litellm` 装包卡死**（0.7.0 之前版本）→ 用 `--no-deps` + 手动补依赖绕开
2. **`timeout` / `max_tokens` kwargs 在 `ChatLiteLLM.__init__` 看不到**（`*args, **kwargs` 签名）→ 归到 `model_kwargs` 字典透传
3. **`create_agent(model=...)` 不接受 Runnable** → 只传 chat model，结构化走 `response_format`
4. **`ainvoke(config=...)` 类型签名要 `RunnableConfig`** → 用 `cast(RunnableConfig, ...)` 标注

### 当前状态（v1.0 已跑通）

- ✅ 端到端：前端输入 → 后端 `create_agent` → MiniMax 生成代码 → 工具验证 + 渲染 → SSE 推 mp4
- ⚠️ 偶发失败：LiteLLM + MiniMax 自身稳定性问题（Connection error / 模型未收敛），需要补 tenacity 重试

### 下一步建议

1. **LiteLLM 重试层**：`tenacity` 包 `acompletion`，网络错自动重试 2 次
2. **补 few-shot**：v1.0 要 3 个算法（冒泡排序已有），补 二分查找 + 图 BFS
3. **Step 5 持久化**：user/history 表 + 历史查询 API + 前端列表
4. **Step 6 压测**：3 算法 × 10 次，统计成功率 + P95 延迟

