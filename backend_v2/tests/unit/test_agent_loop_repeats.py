"""The loop must stop a model from replaying the identical tool call forever."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from xiaoying_quick.application.agent_run.loop import AgentRunService
from xiaoying_quick.infrastructure.llm import ToolCallFragment
from xiaoying_quick.modules.agent import ToolCallResult


def _build_agent() -> tuple[AgentRunService, MagicMock]:
    tools = MagicMock()
    tools.parse_arguments.return_value = {"sql": "SELECT 1"}
    tools.execute = AsyncMock(return_value=ToolCallResult(ok=True, output="执行成功"))
    agent = AgentRunService(
        runs=MagicMock(),
        chats=MagicMock(),
        artifacts=MagicMock(),
        clarifications=MagicMock(),
        model_registry=MagicMock(),
        tools=tools,
        lab_ids=(),
        tool_dependencies={},
        checkpoint=lambda: None,
    )
    return agent, tools


def _call(index: int) -> ToolCallFragment:
    return ToolCallFragment(id=f"call-{index}", name="query_db", arguments='{"sql": "SELECT 1"}')


def test_identical_tool_calls_are_blocked_after_honest_retries() -> None:
    agent, tools = _build_agent()
    messages: list = []
    transcript: list = []
    session = MagicMock()

    outputs = []
    for index in range(5):
        suspended = asyncio.run(
            agent._execute_call(
                actor_id="user-1",
                run_id="run-1",
                session=session,
                step=index + 1,
                call=_call(index),
                messages=messages,
                turn_messages=transcript,
            )
        )
        assert suspended is False
        outputs.append(messages[-1].content)

    # Three honest executions, then the loop refuses to spin any further.
    assert tools.execute.await_count == 3
    assert "已重复 3 次" in outputs[2]
    assert "已经重复 4 次" in outputs[3]
    assert "已经重复 5 次" in outputs[4]


def test_distinct_arguments_still_execute() -> None:
    agent, tools = _build_agent()
    tools.parse_arguments.side_effect = [{"sql": "SELECT 1"}, {"sql": "SELECT 2"}]
    session = MagicMock()

    for index, _sql in enumerate(["SELECT 1", "SELECT 2"]):
        asyncio.run(
            agent._execute_call(
                actor_id="user-1",
                run_id="run-1",
                session=session,
                step=index + 1,
                call=ToolCallFragment(id=f"call-{index}", name="query_db", arguments="{}"),
                messages=[],
                turn_messages=[],
            )
        )
    assert tools.execute.await_count == 2


def test_xlsx_query_reference_survives_more_than_twelve_drilldown_queries() -> None:
    from xiaoying_quick.application.agent_run.chart_tool import build_present_chart_tool
    from xiaoying_quick.modules.agent import AgentToolContext

    agent, tools = _build_agent()
    agent._tool_dependencies["lab_provider"] = "xlsx"
    records = {}

    def append(**kwargs):
        reference = f"artifact_{len(records)}"
        records[reference] = kwargs
        return reference

    agent._artifacts.append.side_effect = append
    agent._artifacts.get.side_effect = records.get
    for index in range(15):
        tools.parse_arguments.return_value = {"sql": f"SELECT {index + 1}"}
        tools.execute.return_value = ToolCallResult(
            ok=True,
            output="查询成功",
            payload={"columns": ["城市", "销售金额"], "rows": [["北京", index + 1]]},
        )
        messages = []
        asyncio.run(
            agent._execute_call(
                actor_id="user-1",
                run_id="run-1",
                session=MagicMock(),
                step=index + 1,
                call=ToolCallFragment(id=f"call-{index}", name="query_db", arguments="{}"),
                messages=messages,
                turn_messages=[],
            )
        )
        reference = next(
            key for key, value in records.items() if value.get("atom_id") == f"call-{index}"
        )
        assert f"query_ref={reference}" in messages[-1].content
    assert len(agent._query_tables) == 12
    events = []
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda kind, payload: events.append(payload),
        extras={"artifacts": agent._artifacts, "query_tables": agent._query_tables},
    )
    chart = asyncio.run(
        build_present_chart_tool().executor(
            context,
            {
                "query_ref": "artifact_0",
                "title": "原始总体查询",
            },
        )
    )
    assert chart.ok
    assert events[0]["kpis"][0]["value"] == 1


def test_fit_event_payload_truncates_oversized_fields_under_the_cap() -> None:
    from xiaoying_quick.application.agent_run.loop import (
        _EVENT_PAYLOAD_BYTES,
        _TRUNCATION_MARKER,
        _fit_event_payload,
    )

    small = {"step": 3, "ok": True, "output": "查询成功"}
    assert _fit_event_payload(small) == small

    huge = {"step": 21, "ok": True, "output": "数" * 80_000, "name": "query_db"}
    fitted = _fit_event_payload(huge)
    encoded = json.dumps(fitted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= _EVENT_PAYLOAD_BYTES
    assert fitted["output"].endswith(_TRUNCATION_MARKER)
    assert fitted["name"] == "query_db"
    assert fitted["step"] == 21


def test_nested_event_payload_cannot_trap_text_truncation_in_a_loop() -> None:
    from xiaoying_quick.application.agent_run.loop import _fit_event_payload

    payload = {"title": "短标题", "rows": [["城市" * 40_000, 1]]}
    assert _fit_event_payload(payload) == payload


def test_structured_analysis_events_preserve_all_chart_data() -> None:
    from xiaoying_quick.modules.runs.service import RunService
    from xiaoying_quick.shared.errors import ValidationFailed

    agent, _ = _build_agent()
    payload = {"version": 2, "title": "完整经营图", "data": {"rows": [["城市" * 40_000, 1]]}}
    agent._emit("run-1", "chart.ready", payload)
    saved = agent._runs.append_event.call_args.kwargs["payload"]
    assert saved == payload
    RunService._validate_event("chart.ready", saved)
    with pytest.raises(ValidationFailed, match="64 KiB"):
        RunService._validate_event("tool.result", saved)
    with pytest.raises(ValidationFailed, match="4 MiB"):
        RunService._validate_event("chart.ready", {**payload, "large": "x" * (4 * 1024 * 1024)})


def test_ask_user_opened_event_carries_canonical_question_and_choice_ids() -> None:
    """Regression: the UI can only submit answers when the opened event
    carries the case's canonical question/choice ids, not the tool's raw
    free-form groups."""

    agent, tools = _build_agent()
    agent._clarifications.for_run.return_value = None
    tools.parse_arguments.return_value = {
        "question": "机构口径？",
        "options": ["全部机构", "仅医院"],
    }
    tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="等待用户澄清",
            payload={
                "groups": [
                    {
                        "question": "机构口径？",
                        "options": [
                            {"label": "全部机构", "recommended": True},
                            {"label": "仅医院"},
                        ],
                        "allow_free_text": True,
                    }
                ]
            },
            suspended=True,
        )
    )
    session = MagicMock()
    session.id = "session-1"

    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=session,
            step=1,
            call=ToolCallFragment(id="call-ask", name="ask_user", arguments="{}"),
            messages=[],
            turn_messages=[],
        )
    )

    opened = [
        call.kwargs["payload"]
        for call in agent._runs.append_event.call_args_list
        if call.kwargs["event_type"] == "ask_user.opened"
    ]
    assert len(opened) == 1
    group = opened[0]["groups"][0]
    assert group["question_id"]
    assert group["prompt"] == "机构口径？"
    assert group["allow_free_text"] is True
    choice_ids = [choice["id"] for choice in group["choices"]]
    assert len(choice_ids) == 2 and all(choice_ids)
    assert [choice["label"] for choice in group["choices"]] == ["全部机构", "仅医院"]
    assert group["choices"][0]["recommended"] is True
