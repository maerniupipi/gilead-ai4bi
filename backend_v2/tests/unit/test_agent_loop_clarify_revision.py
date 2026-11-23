"""A run that suspends twice must not collide on UNIQUE(run_id, revision)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from xiaoying_quick.application.agent_run.loop import AgentRunService
from xiaoying_quick.infrastructure.llm import ToolCallFragment
from xiaoying_quick.modules.agent import ToolCallResult


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


def _build_agent(store: _CaseStore) -> AgentRunService:
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
                        "question": "按哪种口径？",
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
        tool_dependencies={},
        checkpoint=lambda: None,
    )


def test_second_suspension_bumps_revision() -> None:
    store = _CaseStore()
    agent = _build_agent(store)
    session = MagicMock()

    for index in range(2):
        suspended = asyncio.run(
            agent._execute_call(
                actor_id="user-1",
                run_id="run-1",
                session=session,
                step=index + 1,
                call=ToolCallFragment(id=f"call-{index}", name="ask_user", arguments="{}"),
                messages=[],
                turn_messages=[],
            )
        )
        assert suspended is True

    assert [case.version for case in store.cases] == [1, 2]
    assert len({case.case_id for case in store.cases}) == 2


def test_first_suspension_keeps_revision_one() -> None:
    store = _CaseStore()
    agent = _build_agent(store)

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
    assert store.cases[0].version == 1
