"""ask_user accepts one to three clarification questions per suspension."""

from __future__ import annotations

import asyncio

from xiaoying_quick.application.agent_run.tools import _ask_user_groups, build_ask_user_tool
from xiaoying_quick.modules.agent import AgentToolContext, ToolCallResult


def test_multi_question_arguments_become_groups() -> None:
    groups = _ask_user_groups(
        {
            "questions": [
                {"question": "时间窗口？", "options": ["YTD", "H1"]},
                {"question": "统计口径？", "options": ["金额", "盒数"]},
            ]
        }
    )
    assert isinstance(groups, list)
    assert [group["question"] for group in groups] == ["时间窗口？", "统计口径？"]
    assert groups[0]["options"][0] == {"label": "YTD", "recommended": True}
    assert groups[1]["options"][1] == {"label": "盒数", "recommended": False}
    assert all(group["allow_free_text"] for group in groups)


def test_legacy_single_question_still_works() -> None:
    groups = _ask_user_groups({"question": "口径？", "options": ["金额", "盒数"]})
    assert isinstance(groups, list)
    assert len(groups) == 1
    assert groups[0]["question"] == "口径？"


def test_more_than_three_questions_rejected() -> None:
    result = _ask_user_groups(
        {"questions": [{"question": f"问题{i}", "options": ["a", "b"]} for i in range(4)]}
    )
    assert isinstance(result, ToolCallResult)
    assert not result.ok


def test_question_without_enough_options_rejected() -> None:
    result = _ask_user_groups({"questions": [{"question": "时间窗口？", "options": ["只有YTD"]}]})
    assert isinstance(result, ToolCallResult)
    assert not result.ok


def test_missing_question_and_questions_rejected() -> None:
    result = _ask_user_groups({"options": ["a", "b"]})
    assert isinstance(result, ToolCallResult)
    assert not result.ok


def test_multi_select_flag_reaches_the_groups() -> None:
    spec = build_ask_user_tool()
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
    )
    result = asyncio.run(
        spec.executor(
            context,
            {
                "question": "这条口径沉淀到哪里？",
                "options": ["个人记忆", "业务知识", "actual 实验室"],
                "multi_select": True,
            },
        )
    )
    assert result.ok and result.suspended
    groups = result.payload["groups"]
    assert len(groups) == 1
    assert groups[0]["multi_select"] is True
    assert [option["label"] for option in groups[0]["options"]] == [
        "个人记忆",
        "业务知识",
        "actual 实验室",
    ]
