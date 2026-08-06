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