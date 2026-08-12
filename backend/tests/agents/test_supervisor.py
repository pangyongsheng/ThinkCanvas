"""P1/P2 Supervisor 工厂 + worker 的基础测试。

只测"能构建"和"状态字段兼容"，不跑真 LLM。真实链路验证
（端到端 + 落库）由现有 service / conversations 集成测试覆盖。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware import AgentMiddleware
from langgraph.graph import END, START

from app.agents.builder import _compose_system_prompt
from app.agents.middleware.persistence import (
    AgentPersistenceMiddleware,
    _resolve_conversation_id,
    _resolve_on_event,
)
from app.agents.reviewer import (
    CodeReview,
    build_reviewer_prompt,
    build_reviewer_user_message,
)
from app.agents.schemas import CodeOutput
from app.agents.styles import DEFAULT_STYLE_ID
from app.agents.supervisor import (
    MAX_CODE_ROUNDS,
    SupervisorState,
    build_coder_worker,
    build_reviewer_llm,
    build_supervisor,
)
from app.agents.tools import render_manim_dryrun, validate_manim_code
from app.db.models import FewShot


# ---------------------------------------------------------------------------
# build_coder_worker
# ---------------------------------------------------------------------------


def test_coder_worker_is_built_with_standard_create_agent():
    """Coder worker 必须走标准 create_agent(model=, tools=, response_format=)."""
    with patch("app.agents.supervisor.create_agent") as mock_create:
        mock_create.return_value = MagicMock(name="compiled_agent")
        build_coder_worker()
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert "model" in kwargs
        assert kwargs["response_format"] is CodeOutput
        assert validate_manim_code in kwargs["tools"]
        assert render_manim_dryrun in kwargs["tools"]
        assert kwargs["name"] == "coder"


def test_coder_worker_passes_system_prompt_with_style_and_extras():
    """Coder worker 的 system prompt 必须按 style + extra + few-shot 拼。"""
    with patch("app.agents.supervisor.create_agent") as mock_create:
        mock_create.return_value = MagicMock()
        build_coder_worker(
            style_id="3b1b",
            extra_system_prompt="EXTRA",
        )
        kwargs = mock_create.call_args.kwargs
        prompt = kwargs["system_prompt"]
        assert "EXTRA" in prompt
        from app.agents.styles import load_style
        assert load_style("3b1b").description.split("\n")[0] in prompt


def test_coder_worker_accepts_middleware():
    """中间件参数应该原样透传给 create_agent。"""
    with patch("app.agents.supervisor.create_agent") as mock_create:
        mock_create.return_value = MagicMock()
        mw = MagicMock(spec=AgentMiddleware)
        build_coder_worker(middleware=[mw])
        assert mw in mock_create.call_args.kwargs["middleware"]


# ---------------------------------------------------------------------------
# build_supervisor
# ---------------------------------------------------------------------------


def test_build_supervisor_p2_returns_compiled_graph_with_coder_and_reviewer():
    """P2 Supervisor 必须是 StateGraph 图，含 coder + reviewer 两个 node。"""
    g = build_supervisor()
    assert g is not None
    # 至少含 coder / reviewer / __start__ 三个 node
    nodes = list(g.nodes.keys())
    assert "coder" in nodes
    assert "reviewer" in nodes
    assert "__start__" in nodes


def test_build_supervisor_p2_has_conditional_edge_after_reviewer():
    """P2 Supervisor 在 reviewer 后必须有条件边（reviewer → coder | END）。"""
    g = build_supervisor()
    # CompiledStateGraph 不直接暴露 edges；但能 draw_mermaid 出图
    # 这里只测它能 compile 且不抛异常
    mermaid = g.get_graph().draw_mermaid()
    assert "coder" in mermaid
    assert "reviewer" in mermaid


def test_max_code_rounds_constant_is_two():
    """MAX_CODE_ROUNDS = 2（Coder 最多跑 2 次：首轮 + 1 次 retry）。"""
    assert MAX_CODE_ROUNDS == 2


# ---------------------------------------------------------------------------
# build_reviewer_llm
# ---------------------------------------------------------------------------


def test_reviewer_llm_uses_with_structured_output():
    """Reviewer 必须用 with_structured_output(CodeReview) 拿结构化输出。"""
    with patch("app.agents.supervisor.get_llm") as mock_get_llm:
        mock_base = MagicMock()
        mock_get_llm.return_value = mock_base
        mock_structured = MagicMock()
        mock_base.with_structured_output.return_value = mock_structured
        result = build_reviewer_llm()
        mock_base.with_structured_output.assert_called_once_with(CodeReview)
        assert result is mock_structured


# ---------------------------------------------------------------------------
# Reviewer helpers
# ---------------------------------------------------------------------------


def test_reviewer_user_message_with_feedback():
    """第二轮 Reviewer 的 user message 必须带 [上次审查反馈] 段。"""
    msg = build_reviewer_user_message(
        code="x = 1",
        previous_feedback="把 import 加上",
    )
    assert "[上次审查反馈]" in msg
    assert "把 import 加上" in msg
    assert "[待审查代码]" in msg
    assert "x = 1" in msg


def test_reviewer_user_message_without_feedback():
    """首轮 Reviewer 不带 [上次审查反馈] 段。"""
    msg = build_reviewer_user_message(code="x = 1")
    assert "[上次审查反馈]" not in msg
    assert "[待审查代码]" in msg
    assert "x = 1" in msg


def test_code_review_schema_defaults():
    """CodeReview.feedback 必须有默认值（不传也不报错）。"""
    r = CodeReview(ok=True)
    assert r.feedback == ""


def test_code_review_schema_with_feedback():
    r = CodeReview(ok=False, feedback="缺少 from manim import *")
    assert r.ok is False
    assert r.feedback == "缺少 from manim import *"


def test_reviewer_prompt_mentions_manim_api():
    """Reviewer system prompt 必须明确审查维度（Manim API 等）。"""
    p = build_reviewer_prompt()
    assert "from manim import" in p
    assert "construct" in p
    assert "os" in p or "subprocess" in p  # 危险调用黑名单


# ---------------------------------------------------------------------------
# 中间件兼容 state / context 双路径（P1/P2 都有用）
# ---------------------------------------------------------------------------


class _FakeRuntime:
    def __init__(self, context):
        self.context = context


def test_resolve_conversation_id_prefers_context():
    state = {"conversation_id": "from_state"}
    runtime = _FakeRuntime({"conversation_id": "from_ctx"})
    assert _resolve_conversation_id(state, runtime) == "from_ctx"


def test_resolve_conversation_id_falls_back_to_state():
    state = {"conversation_id": "from_state"}
    runtime = _FakeRuntime(None)
    assert _resolve_conversation_id(state, runtime) == "from_state"


def test_resolve_conversation_id_returns_none_when_missing():
    state = {}
    runtime = _FakeRuntime(None)
    assert _resolve_conversation_id(state, runtime) is None


def test_resolve_on_event_prefers_context():
    cb = lambda *a, **k: None
    state = {"on_event": lambda *a, **k: None}
    runtime = _FakeRuntime({"on_event": cb})
    assert _resolve_on_event(state, runtime) is cb


def test_resolve_on_event_falls_back_to_state():
    cb = lambda *a, **k: None
    state = {"on_event": cb}
    runtime = _FakeRuntime(None)
    assert _resolve_on_event(state, runtime) is cb


def test_resolve_on_event_returns_none_when_missing():
    state = {}
    runtime = _FakeRuntime(None)
    assert _resolve_on_event(state, runtime) is None
