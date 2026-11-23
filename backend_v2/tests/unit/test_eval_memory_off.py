from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from xiaoying_quick.application.agent_run.loop import AgentRunService, _resolve_use_memory
from xiaoying_quick.application.agent_run.tools import (
    build_knowledge_search_tool,
    build_memory_save_tool,
)
from xiaoying_quick.modules.agent import AgentToolContext
from xiaoying_quick.modules.context import RecallLevel, RecallRequest, RecallSourceType


def _context(**extras) -> AgentToolContext:
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras=extras,
    )


def test_resolve_use_memory_prefers_explicit_false() -> None:
    assert _resolve_use_memory(False, {"use_memory": True}) is False
    assert _resolve_use_memory(None, {"use_memory": False}) is False
    assert _resolve_use_memory(None, {}) is False
    assert _resolve_use_memory(True, {"use_memory": True}) is False


def test_knowledge_search_excludes_personal_memory_when_disabled() -> None:
    captured: dict[str, RecallRequest] = {}

    class Broker:
        def recall(self, request: RecallRequest, performed_at: datetime):
            del performed_at
            captured["request"] = request
            return SimpleNamespace(items=[])

    result = asyncio.run(
        build_knowledge_search_tool().executor(
            _context(context_broker=Broker(), use_memory=False),
            {"query": "安达唐口径"},
        )
    )
    assert result.ok is True
    allowed = captured["request"].allowed_source_types
    assert allowed is not None
    assert RecallSourceType.PERSONAL_MEMORY not in allowed
    assert RecallSourceType.BUSINESS_KNOWLEDGE in allowed
    assert captured["request"].level is RecallLevel.L1_UNDERSTANDING


def test_memory_save_is_skipped_when_memory_is_off() -> None:
    writer = MagicMock()
    result = asyncio.run(
        build_memory_save_tool().executor(
            _context(memory_writer=writer, use_memory=False),
            {
                "scope": "personal",
                "content": "查询倍择瑞相关问题时，默认只查重点民营机构的数据。",
                "category": "scope",
            },
        )
    )
    assert result.ok is True
    assert result.payload["skipped"] is True
    writer.write.assert_not_called()


def test_clarification_auto_save_is_skipped_when_memory_is_off() -> None:
    writer = MagicMock()
    agent = AgentRunService(
        runs=MagicMock(),
        chats=MagicMock(),
        artifacts=MagicMock(),
        clarifications=MagicMock(),
        model_registry=MagicMock(),
        tools=MagicMock(),
        lab_ids=(),
        tool_dependencies={"memory_writer": writer},
        checkpoint=lambda: None,
    )
    agent._use_memory = False
    case = SimpleNamespace(
        case_id="case-1",
        questions=(SimpleNamespace(prompt="口径？"),),
    )
    agent._remember_clarification(
        actor_id="user-1",
        run_id="run-1",
        case=case,
        answer="金额",
        checkpoint={"turn_messages": []},
        answered=(("口径？", "金额"),),
    )
    writer.write.assert_not_called()
    assert not any(
        call.kwargs.get("event_type") == "memory.auto_saved"
        or (len(call.args) > 1 and str(call.args[1]) == "memory.auto_saved")
        for call in agent._runs.append_event.call_args_list
    )
