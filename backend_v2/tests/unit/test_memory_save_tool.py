"""memory_save must route personal preferences to memory and shared scopes to review."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from xiaoying_quick.application.agent_run.tools import build_memory_save_tool
from xiaoying_quick.modules.agent import AgentToolContext
from xiaoying_quick.modules.knowledge import KnowledgeScope


def _context(writer: MagicMock, proposer: MagicMock) -> AgentToolContext:
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras={"memory_writer": writer, "knowledge_proposer": proposer},
    )


def _run(writer: MagicMock, proposer: MagicMock, arguments: dict):
    spec = build_memory_save_tool()
    return asyncio.run(spec.executor(_context(writer, proposer), arguments))


def test_personal_scope_writes_memory_entry() -> None:
    writer = MagicMock()
    writer.write.return_value = SimpleNamespace(id="mem-1")
    result = _run(
        writer,
        MagicMock(),
        {
            "scope": "personal",
            "content": "查询倍择瑞相关问题时，默认只查重点民营机构的数据。",
            "category": "scope",
        },
    )
    assert result.ok is True
    request = writer.write.call_args.args[1]
    assert request.category == "scope"
    assert "重点民营机构" in request.content
    assert request.source_run_id == "run-1"
    assert writer.write.call_args.args[0] == "user-1"
    assert result.payload["scope"] == "personal"
    assert result.payload["entry_id"] == "mem-1"
    assert "立即生效" in result.output


def test_review_scope_proposes_a_knowledge_candidate() -> None:
    proposer = MagicMock()
    proposer.propose.return_value = SimpleNamespace(id="candidate-1")
    result = _run(
        MagicMock(),
        proposer,
        {
            "scope": "review",
            "title": "YoY 口径",
            "content": "YoY GR% =（本期销量 / 去年同期销量）- 1，按自然月对齐。",
            "why": "用户确认",
        },
    )
    assert result.ok is True
    request = proposer.propose.call_args.args[1]
    assert request.scope is KnowledgeScope.BUSINESS
    assert request.title == "YoY 口径"
    assert request.rationale == "【去向：通用业务知识】用户确认"
    assert "run:run-1" in request.evidence_refs
    assert "target:business" in request.evidence_refs
    assert result.payload["scope"] == "review"
    assert result.payload["entry_id"] == "candidate-1"
    assert "审核" in result.output


def test_review_scope_routes_to_a_lab_document() -> None:
    proposer = MagicMock()
    proposer.propose.return_value = SimpleNamespace(id="candidate-2")
    result = _run(
        MagicMock(),
        proposer,
        {
            "scope": "review",
            "title": "PDOT 口径",
            "content": "PDOT 指分子内份额，按外部市场表 value_type 过滤。",
            "target": "ext_complex",
        },
    )
    assert result.ok is True
    request = proposer.propose.call_args.args[1]
    assert request.rationale.startswith("【去向：外部市场·复杂 实验室】")
    assert "target:ext_complex" in request.evidence_refs
    assert result.payload["target"] == "ext_complex"
    assert "外部市场·复杂" in result.output


def test_review_scope_rejects_an_unknown_target() -> None:
    result = _run(
        MagicMock(),
        MagicMock(),
        {
            "scope": "review",
            "title": "标题",
            "content": "一条足够长的共享口径描述内容。",
            "target": "nowhere",
        },
    )
    assert result.ok is False


def test_review_scope_requires_a_title() -> None:
    result = _run(
        MagicMock(),
        MagicMock(),
        {"scope": "review", "content": "一条足够长的共享口径描述内容。"},
    )
    assert result.ok is False
    assert "title" in result.output


def test_unknown_scope_is_rejected() -> None:
    result = _run(MagicMock(), MagicMock(), {"scope": "team", "content": "任意内容"})
    assert result.ok is False


def test_too_short_content_is_rejected() -> None:
    result = _run(MagicMock(), MagicMock(), {"scope": "personal", "content": "短"})
    assert result.ok is False


def test_unknown_category_falls_back_to_preference() -> None:
    writer = MagicMock()
    writer.write.return_value = SimpleNamespace(id="mem-2")
    result = _run(
        writer,
        MagicMock(),
        {
            "scope": "personal",
            "content": "用户更喜欢先看省级汇总再看城市明细。",
            "category": "未知",
        },
    )
    assert result.ok is True
    assert writer.write.call_args.args[1].category == "preference"
