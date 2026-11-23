"""Answered clarifications must land in the asker's personal memory."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from xiaoying_quick.application.agent_run.loop import AgentRunService
from xiaoying_quick.infrastructure.llm import ToolCallFragment
from xiaoying_quick.modules.agent import ToolCallResult
from xiaoying_quick.modules.knowledge.contracts import MemoryWriteRequest


class _CaseStore:
    """In-memory stand-in for the clarification repository."""

    def __init__(self) -> None:
        self.cases: list = []

    def get(self, case_id: str):
        return next((case for case in self.cases if case.case_id == case_id), None)

    def for_run(self, run_id: str):
        matches = [case for case in self.cases if case.run_id == run_id]
        return max(matches, key=lambda case: case.version) if matches else None

    def save(self, case) -> None:
        existing = self.get(case.case_id)
        if existing is not None:
            self.cases[self.cases.index(existing)] = case
        else:
            self.cases.append(case)


def _build_agent(store: _CaseStore, writer: MagicMock) -> AgentRunService:
    tools = MagicMock()
    tools.parse_arguments.return_value = {"question": "口径？"}
    tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="已向用户提问，等待用户选择后继续。",
            suspended=True,
            payload={
                "groups": [
                    {
                        "question": "耐信用哪个口径统计？",
                        "options": [{"label": "金额"}, {"label": "盒数"}],
                        "allow_free_text": True,
                    }
                ]
            },
        )
    )
    return AgentRunService(
        runs=MagicMock(),
        chats=MagicMock(),
        artifacts=MagicMock(),
        clarifications=store,
        model_registry=MagicMock(),
        tools=tools,
        lab_ids=(),
        tool_dependencies={"memory_writer": writer},
        checkpoint=lambda: None,
    )


def _suspend_once(agent: AgentRunService, store: _CaseStore):
    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=MagicMock(),
            step=1,
            call=ToolCallFragment(id="call-1", name="ask_user", arguments="{}"),
            messages=[],
            turn_messages=[],
        )
    )
    return store.cases[0]


def _event_types(agent: AgentRunService) -> list[str]:
    types = []
    for call in agent._runs.append_event.call_args_list:
        if "event_type" in call.kwargs:
            types.append(str(call.kwargs["event_type"]))
        elif len(call.args) > 1:
            types.append(str(call.args[1]))
    return types


def test_answered_clarification_is_saved_to_personal_memory() -> None:
    store = _CaseStore()
    writer = MagicMock()
    writer.write.return_value = MagicMock(id="mem-1", category="scope")
    agent = _build_agent(store, writer)
    case = _suspend_once(agent, store)

    checkpoint = {"turn_messages": [{"role": "user", "content": "耐信 H2 新增准入怎么测算？"}]}
    agent._remember_clarification(
        actor_id="user-1",
        run_id="run-1",
        case=case,
        answer="金额",
        checkpoint=checkpoint,
    )

    writer.write.assert_called_once()
    actor, request = writer.write.call_args.args
    assert actor == "user-1"
    assert isinstance(request, MemoryWriteRequest)
    assert request.category == "scope"
    assert request.source_run_id == "run-1"
    assert "耐信 H2 新增准入怎么测算？" in request.content
    assert "耐信用哪个口径统计？" in request.content
    assert "金额" in request.content

    assert "memory.auto_saved" in _event_types(agent)


def test_missing_memory_writer_is_a_noop() -> None:
    store = _CaseStore()
    agent = _build_agent(store, MagicMock())
    agent._tool_dependencies = {}
    case = _suspend_once(agent, store)

    agent._remember_clarification(
        actor_id="user-1",
        run_id="run-1",
        case=case,
        answer="金额",
        checkpoint={"turn_messages": []},
    )

    assert "memory.auto_saved" not in _event_types(agent)


def test_writer_failure_does_not_break_the_resume() -> None:
    store = _CaseStore()
    writer = MagicMock()
    writer.write.side_effect = RuntimeError("boom")
    agent = _build_agent(store, writer)
    case = _suspend_once(agent, store)

    agent._remember_clarification(
        actor_id="user-1",
        run_id="run-1",
        case=case,
        answer="金额",
        checkpoint={"turn_messages": []},
    )

    assert "memory.auto_saved" not in _event_types(agent)
