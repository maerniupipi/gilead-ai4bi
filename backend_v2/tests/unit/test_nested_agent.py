from __future__ import annotations

import asyncio

from xiaoying_quick.application.agent_run.nested import NestedAgentRunner
from xiaoying_quick.infrastructure.llm import AssistantTurn, ContentDelta, TurnComplete
from xiaoying_quick.modules.agent import AgentToolContext, ToolCallResult, ToolRegistry, ToolSpec
from xiaoying_quick.modules.agent.catalog import AGENT_BY_ID
from xiaoying_quick.modules.agent.profiles import AgentConfigRecord
from xiaoying_quick.modules.agent.service import AgentConfigService


class MemoryRepo:
    def __init__(self) -> None:
        self.rows: dict[str, AgentConfigRecord] = {}

    def get(self, agent_id: str) -> AgentConfigRecord | None:
        return self.rows.get(agent_id)

    def list_all(self) -> tuple[AgentConfigRecord, ...]:
        return tuple(self.rows.values())

    def add(self, record: AgentConfigRecord) -> AgentConfigRecord:
        self.rows[record.id] = record
        return record

    def save(self, record: AgentConfigRecord) -> AgentConfigRecord:
        self.rows[record.id] = record
        return record


class FakeClient:
    def __init__(self) -> None:
        self.tools: list | None = None

    async def stream_chat(self, *, purpose, messages, tools=None, max_tokens=None):
        del purpose, messages, max_tokens
        self.tools = list(tools or [])
        yield ContentDelta(text="候选 SQL：SELECT 1")
        yield TurnComplete(
            turn=AssistantTurn(
                content="候选 SQL：SELECT 1",
                reasoning="核对口径后直接给出。",
                tool_calls=(),
                finish_reason="stop",
                usage={"total_tokens": 9},
            )
        )


def test_nested_runner_emits_scoped_events_and_returns_answer() -> None:
    asyncio.run(_run_nested())


async def _run_nested() -> None:
    events: list[tuple[str, dict]] = []
    client = FakeClient()
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: events.append((event_type, payload)),
        extras={"llm_client": client},
        call_id="delegate-1",
    )
    spec = AGENT_BY_ID["lab_sql"]

    async def unused(_context, _arguments):
        return ToolCallResult(ok=True, output="unused")

    tools = ToolRegistry(
        (
            ToolSpec(
                name="ask_lab",
                description="lab",
                parameters={"type": "object", "properties": {}},
                executor=unused,
            ),
        )
    )
    result = await NestedAgentRunner(lab_ids=("actual",)).run(
        context=context,
        spec=spec,
        tools=tools,
        arguments={"question": "倍择瑞院外销量", "lab_id": "actual"},
    )
    assert result.ok is True
    assert "SELECT 1" in result.output
    kinds = [event_type for event_type, _ in events]
    assert "agent.turn_start" in kinds
    assert "agent.done" in kinds
    for _event_type, payload in events:
        assert payload["parent_call_id"] == "delegate-1"
        assert payload["agent_id"] == "lab_sql"
    assert client.tools is not None


def test_assemble_includes_delegate_when_main_selects_sub_agent() -> None:
    from xiaoying_quick.application.agent_run.assembly import assemble_tool_registry
    from xiaoying_quick.modules.agent.catalog import TOOL_NAMES

    async def execute(_context, _arguments):
        return ToolCallResult(ok=True, output="ok")

    primitives = {
        name: ToolSpec(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            executor=execute,
        )
        for name in TOOL_NAMES
    }
    service = AgentConfigService(MemoryRepo())
    service.update("main", agent_names=("lab_sql",))
    registry = assemble_tool_registry(
        service=service,
        primitives=primitives,
        lab_ids=("actual",),
    )
    assert "query_db" in registry.names()
    assert "agent_lab_sql" in registry.names()
