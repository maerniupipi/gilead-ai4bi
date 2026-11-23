"""Excel clarification suspends, resumes and retains only matching file definitions."""

from __future__ import annotations

import io
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock

from openpyxl import Workbook

from xiaoying_quick.application.agent_run.loop import AgentRunService
from xiaoying_quick.infrastructure.llm import AssistantTurn, ToolCallFragment, TurnComplete
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.chat import (
    SqlAlchemyChatRepository,
    SqlAlchemyClarificationRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.modules.clarification import (
    ClarificationAnswer,
    ClarificationCase,
    ClarificationQuestion,
    ClarificationReason,
    ClarificationStatus,
)
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.modules.runs.service import RunService


def test_clarification_and_history_are_scoped_to_the_same_workbooks(app, seed_user):
    owner = seed_user("xlsx-scope-owner")
    principal = IdentityService.principal_from_user(owner)
    now = datetime.now(timezone.utc)
    with app.state.session_factory() as db:
        SqlAlchemyChatRepository(db).create_session("session-scope", owner.id, "不同文件的口径")
        runs = RunService(SqlAlchemyRunRepository(db))
        artifacts = SqlAlchemyArtifactRepository(db)
        cases = SqlAlchemyClarificationRepository(db)
        for index, (files, unit) in enumerate([
            (["file-a", "file-b"], "元"),
            (["file-b", "file-a"], "万元"),
            (["file-c"], "美元"),
        ]):
            run = runs.create_run(
                principal=principal, question="金额单位", session_id="session-scope",
                idempotency_key=None, insight_meta={"chatbot_id": "xlsx", "workbook_ids": files},
            ).run
            question = ClarificationQuestion(
                question_id=f"question-{index}", prompt="金额是什么单位？",
                reason=ClarificationReason.CRITICAL_SLOT_AMBIGUITY,
                choices=(), allow_free_text=True,
            )
            case = ClarificationCase.open(
                case_id=f"case-{index}", run_id=run.id, session_id="session-scope",
                frame_id=run.id, questions=(question,), created_at=now,
            )
            cases.save(replace(
                case, status=ClarificationStatus.ANSWERED, answered_at=now,
                answers=(ClarificationAnswer(
                    question_id=question.question_id, free_text=unit, answered_at=now,
                ),),
            ))
            artifacts.append(run_id=run.id, kind="agent_transcript", payload={
                "status": "completed", "ledger": [{"kind": "scope", "text": unit}],
            })
        db.commit()
        matching = cases.list_answered_for_session(
            "session-scope", workbook_ids=["file-a", "file-b"], limit=1,
        )
        assert matching[0].answers[0].free_text == "万元"
        transcript = artifacts.list_for_session(
            session_id="session-scope", kind="agent_transcript",
            workbook_ids=["file-a", "file-b"], limit=1,
        )
        assert transcript[0]["ledger"][0]["text"] == "万元"
        agent = AgentRunService(
            runs=runs, chats=MagicMock(), artifacts=artifacts, clarifications=cases,
            model_registry=MagicMock(), tools=MagicMock(), lab_ids=(),
            tool_dependencies={"workbook_ids": ["file-a", "file-b"]}, checkpoint=lambda: None,
        )
        scopes = agent._session_clarified_scopes("session-scope")
        assert len(scopes) == 1 and "万元" in scopes[0][1]
        assert "美元" not in str(scopes)


def test_xlsx_inspection_clarification_resume_and_followup(
    settings, app, client, seed_user, auth_headers,
):
    settings.chatbot_mode = "xlsx"
    seed_user("xlsx-clarifier")
    headers = auth_headers("xlsx-clarifier")
    book = Workbook()
    book.active.append(["月份", "开票金额", "回款金额", "目标"])
    book.active.append(["2026-09", 100, 70, 200])
    book.active.append(["2026-10", 120, 90, 200])
    output = io.BytesIO()
    book.save(output)
    uploaded = client.post(
        "/api/v2/chatbots/xlsx/workbooks", headers=headers,
        files={"file": ("未知口径.xlsx", output.getvalue())},
    ).json()
    table = uploaded["sheets"][0]["table"]

    class Model:
        async def stream_chat(self, *, messages, **kwargs):
            replies = {turn.tool_call_id: turn.content for turn in messages if turn.role == "tool"}
            latest_question = next(
                turn.content for turn in reversed(messages) if turn.role == "user"
            )
            if "同一口径" in latest_question:
                scopes = "\n".join(turn.content for turn in messages if turn.role == "system")
                assert "用户确认" in scopes and "万元" in scopes and "开票金额" in scopes
                if "followup-query" not in replies:
                    name, call_id = "query_db", "followup-query"
                    arguments = {"sql": f'SELECT SUM("开票金额") AS "销售金额" FROM "{table}"'}
                else:
                    yield TurnComplete(AssistantTurn(
                        content="按已确认口径合计220万元。", reasoning="",
                        tool_calls=(), finish_reason="stop",
                    ))
                    return
            elif "inspect" not in replies:
                name, call_id = "inspect_workbook", "inspect"
                arguments = {"table": table, "columns": ["开票金额", "回款金额", "目标"]}
            elif "clarify" not in replies:
                profile = json.loads(replies["inspect"])
                assert profile["row_count"] == 2
                name, call_id = "ask_user", "clarify"
                arguments = {"questions": [
                    {"question": "未知口径.xlsx的销售额采用哪个字段？",
                     "why": "开票和回款金额不同，会改变销售额与达成率。",
                     "options": ["开票金额", "回款金额"]},
                    {"question": "开票金额、回款金额和目标的原值单位是什么？",
                     "why": "文件未注明单位，不能将原值直接标成元。",
                     "options": ["万元", "元", "暂不确定"]},
                ]}
            elif "query" not in replies:
                assert "开票金额" in replies["clarify"] and "万元" in replies["clarify"]
                name, call_id = "query_db", "query"
                arguments = {"sql": f'''SELECT "月份", SUM("开票金额") AS "销售金额",
                    SUM("目标") AS "目标金额", 1.0*SUM("开票金额")/SUM("目标") AS "达成率"
                    FROM "{table}" GROUP BY "月份"'''}
            elif "chart" not in replies:
                name, call_id = "present_chart", "chart"
                reference = re.search(r"query_ref=(\w+)", replies["query"]).group(1)
                arguments = {
                    "query_ref": reference, "title": "已确认的销售达成", "dimension": "月份",
                    "scope": "2026年9—10月，开票金额与目标均为万元",
                    "metrics": [
                        {"column": "销售金额", "unit": "万元"},
                        {"column": "目标金额", "unit": "万元"},
                        {"column": "达成率", "unit": "%", "numerator": "销售金额",
                         "denominator": "目标金额"},
                    ],
                }
            else:
                yield TurnComplete(AssistantTurn(
                    content="销售220万元，目标400万元，达成55%。", reasoning="",
                    tool_calls=(), finish_reason="stop",
                ))
                return
            yield TurnComplete(AssistantTurn(
                content="", reasoning="",
                tool_calls=(ToolCallFragment(
                    id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False),
                ),), finish_reason="tool_calls",
            ))

        async def aclose(self):
            pass

    model = Model()

    class Registry:
        def active_client(self):
            return model

    app.state.model_registry = Registry()
    accepted = client.post("/api/v2/chat", headers=headers, json={
        "question": "分析未知口径.xlsx的月度销售达成", "chatbot_id": "xlsx",
    }).json()
    run_id = accepted["run_id"]
    waiting = client.get(
        "/api/v2/clarifications/waiting", headers=headers, params={"run_id": run_id},
    ).json()[0]
    assert len(waiting["groups"]) == 2
    assert waiting["groups"][0]["why"]
    assert not any(
        choice["recommended"] for group in waiting["groups"] for choice in group["choices"]
    )
    events = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()["items"]
    assert [event["payload"]["name"] for event in events if event["type"] == "tool.call"] == [
        "inspect_workbook", "ask_user",
    ]
    answered = client.post(
        f"/api/v2/clarifications/{waiting['case_id']}/answers", headers=headers,
        json={"answers": [
            {"question_id": waiting["groups"][0]["question_id"], "free_text": "开票金额"},
            {"question_id": waiting["groups"][1]["question_id"], "free_text": "万元"},
        ]},
    )
    assert answered.status_code == 202
    assert client.get(f"/api/v2/runs/{run_id}", headers=headers).json()["status"] == "completed"
    events = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()["items"]
    chart = next(event["payload"] for event in events if event["type"] == "chart.ready")
    assert chart["kpis"][0]["value"] == 220 and chart["kpis"][0]["unit"] == "万元"
    followup = client.post("/api/v2/chat", headers=headers, json={
        "question": "同一口径再查一次销售金额", "chatbot_id": "xlsx",
        "session_id": accepted["session_id"],
    }).json()
    followup_path = f"/api/v2/runs/{followup['run_id']}"
    assert client.get(followup_path, headers=headers).json()["status"] == "completed"
    events = client.get(f"{followup_path}/events", headers=headers).json()["items"]
    calls = [event["payload"]["name"] for event in events if event["type"] == "tool.call"]
    assert calls == ["query_db"]
