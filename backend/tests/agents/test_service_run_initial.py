"""AgentService.run_initial 单元测试 — P3 scripting 阶段不强制要 assistant_message。

修复点：run_initial 默认 phase=scripting，图走 Script Designer 路径停在那
— Coder 没跑，middleware 没建 assistant 壳，_require_message 不能再硬性
要求。Scripting 阶段返回 assistant_message=None；coding 阶段照旧断言。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.service import AgentService, AgentRunResult
from app.agents.supervisor import PHASE_CODING, PHASE_SCRIPTING


def _conv_stub(id_="01CONV"):
    """假 Conversation — service 只读 .id 字段。"""
    return SimpleNamespace(id=id_, title="p", style="3b1b", user_id="U1")


def _msg_stub(id_="01MSG", role="user", content="hi"):
    """假 Message — service 只读 .id / .code / .scene_name。"""
    return SimpleNamespace(
        id=id_, role=role, content=content, code=None, scene_name=None,
    )


def _make_service() -> AgentService:
    """构造 AgentService 并把 3 个 DAO 全 mock 掉。"""
    svc = AgentService.__new__(AgentService)
    svc.session = MagicMock()
    svc.dao_conv = MagicMock()
    svc.dao_msg = MagicMock()
    svc.dao_steps = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_run_initial_scripting_phase_allows_none_assistant():
    """Scripting 阶段 Coder 没跑 → assistant_msg 为 None，run_initial 不抛错。"""
    svc = _make_service()
    svc.dao_conv.create = AsyncMock(return_value=_conv_stub())
    svc.dao_conv.set_phase = AsyncMock(return_value=None)
    svc.dao_conv.update_after_run = AsyncMock(return_value=None)
    svc.dao_msg.append_user_message = AsyncMock(return_value=_msg_stub("01USER"))

    script_payload = {
        "title": "傅里叶变换",
        "concept": "信号分解",
        "total_duration_sec": 20.0,
        "style": "3b1b",
        "scenes": [{"index": 0, "duration_sec": 10.0, "description": "x" * 10, "animation": "y" * 5}],
    }
    run_state = {
        "phase": PHASE_SCRIPTING,
        "current_script": script_payload,
        "need_script": True,
    }

    async def _fake_run_agent(*_args, **_kwargs):
        # 关键：assistant_msg=None，模拟 Script Designer 停了的场景
        return None, run_state

    with patch.object(AgentService, "_run_agent", _fake_run_agent):
        result = await svc.run_initial(
            user_id="U1", prompt="解释傅里叶变换", style="3b1b",
        )

    assert isinstance(result, AgentRunResult)
    assert result.phase == PHASE_SCRIPTING
    assert result.script == script_payload
    assert result.need_script is True
    assert result.assistant_message is None  # scripting 阶段允许 None
    assert result.code is None
    assert result.scene_name is None
    # user_message 还是照常建
    assert result.user_message.id == "01USER"
    # current_script 必须写回 DB
    svc.dao_conv.update_after_run.assert_awaited_once()
    call_kwargs = svc.dao_conv.update_after_run.call_args.kwargs
    assert call_kwargs["phase"] == PHASE_SCRIPTING
    assert call_kwargs["current_script"] == script_payload


@pytest.mark.asyncio
async def test_run_initial_coding_phase_requires_assistant():
    """Coding 阶段 Coder 跑过 → assistant_msg 必有；缺了 RuntimeError。"""
    svc = _make_service()
    svc.dao_conv.create = AsyncMock(return_value=_conv_stub())
    svc.dao_conv.set_phase = AsyncMock(return_value=None)
    svc.dao_conv.update_after_run = AsyncMock(return_value=None)
    svc.dao_msg.append_user_message = AsyncMock(return_value=_msg_stub())

    run_state = {
        "phase": PHASE_CODING,
        "code": "from manim import *\nclass S(Scene): pass",
    }

    async def _fake_run_agent_missing(*_args, **_kwargs):
        # assistant_msg=None + phase=coding — 应该被 _require_message 拦下
        return None, run_state

    with patch.object(AgentService, "_run_agent", _fake_run_agent_missing):
        with pytest.raises(RuntimeError, match="no assistant message"):
            await svc.run_initial(
                user_id="U1", prompt="冒泡排序", style="3b1b",
            )


@pytest.mark.asyncio
async def test_run_initial_coding_phase_with_assistant_succeeds():
    """Coding 阶段有 assistant_msg → 正常返回。"""
    svc = _make_service()
    svc.dao_conv.create = AsyncMock(return_value=_conv_stub())
    svc.dao_conv.set_phase = AsyncMock(return_value=None)
    svc.dao_conv.update_after_run = AsyncMock(return_value=None)
    svc.dao_msg.append_user_message = AsyncMock(return_value=_msg_stub())

    asst = SimpleNamespace(
        id="01AST", role="assistant", content="x",
        code="from manim import *\nclass S(Scene): pass",
        scene_name="S",
    )
    run_state = {"phase": PHASE_CODING, "code": asst.code}

    async def _fake_run_agent(*_args, **_kwargs):
        return asst, run_state

    with patch.object(AgentService, "_run_agent", _fake_run_agent):
        result = await svc.run_initial(
            user_id="U1", prompt="冒泡排序", style="3b1b",
        )

    assert result.assistant_message is asst
    assert result.code == asst.code
    assert result.scene_name == "S"
    assert result.phase == PHASE_CODING
    assert result.script is None
    assert result.need_script is False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 回归保护：build_supervisor 必须收到正确的 phase（用户报过的 confirm 500）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_after_confirm_passes_coding_phase_to_run_agent():
    """``run_after_confirm`` 必须把 ``phase=PHASE_CODING`` 传给 ``_run_agent``。"""
    svc = _make_service()
    svc.dao_conv.get = AsyncMock(return_value=SimpleNamespace(
        id="01C", title="x", style="3b1b", user_id="U1",
        phase=PHASE_SCRIPTING, current_script={"title": "t"},
    ))
    svc.dao_conv.set_phase = AsyncMock(return_value=None)
    svc.dao_conv.update_after_run = AsyncMock(return_value=None)

    captured: dict = {}

    async def _spy_run_agent(*args, **kwargs):
        captured["phase"] = kwargs.get("phase")
        # 模拟 Coder 跑了 — 返回 assistant + coding 状态
        asst = SimpleNamespace(
            id="01AST", role="assistant", content="x",
            code="from manim import *\nclass S(Scene): pass", scene_name="S",
        )
        return (
            asst,
            {"phase": PHASE_CODING, "code": "from manim import *\nclass S(Scene): pass"},
        )

    with patch.object(AgentService, "_run_agent", _spy_run_agent):
        await svc.run_after_confirm(
            conversation_id="01C", user_id="U1", few_shots=[],
        )

    assert captured["phase"] == PHASE_CODING, (
        f"confirm 应透传 PHASE_CODING，实际 {captured.get('phase')!r}"
    )


def test_run_agent_signature_passes_phase_to_build_supervisor():
    """``_run_agent`` 必须把收到的 ``phase`` 透传给 ``build_supervisor``。

    静态扫描源码 — 防回归成本最低的方式（不用造 spy 图）。
    漏传的话 confirm 路径 500（用户已踩过）。
    """
    import inspect
    from app.agents.service import AgentService

    src = inspect.getsource(AgentService._run_agent)
    # build_supervisor(...) 调用里必须有 phase=phase
    assert "build_supervisor(" in src, "_run_agent 没调 build_supervisor？"
    # 提取 build_supervisor(...) 这一段
    idx = src.index("build_supervisor(")
    snippet = src[idx:idx + 400]
    assert "phase=phase" in snippet, (
        "_run_agent 调 build_supervisor 时没把 phase 透传出去，"
        "会导致 confirm 路径 500（先跑 script_decision，Coder 没机会跑，"
        "_require_message 抛 RuntimeError）。"
    )


@pytest.mark.asyncio
async def test_run_initial_default_phase_scripting():
    """run_initial 默认 phase=scripting（不传 phase 时）。"""
    svc = _make_service()
    svc.dao_conv.create = AsyncMock(return_value=_conv_stub())
    svc.dao_conv.set_phase = AsyncMock(return_value=None)
    svc.dao_conv.update_after_run = AsyncMock(return_value=None)
    svc.dao_msg.append_user_message = AsyncMock(return_value=_msg_stub())

    captured: dict = {}

    async def _spy_run_agent(*args, **kwargs):
        captured["phase"] = kwargs.get("phase")
        return None, {"phase": PHASE_SCRIPTING, "current_script": {"title": "t"}}

    with patch.object(AgentService, "_run_agent", _spy_run_agent):
        await svc.run_initial(user_id="U1", prompt="x", style="3b1b")

    assert captured["phase"] == PHASE_SCRIPTING

