"""One real SQL query and both chat modes through the same durable loop, offline."""

import json
import sqlite3

import pytest

from xiaoying_quick.bootstrap import container
from xiaoying_quick.infrastructure.llm.client import (
    AssistantTurn,
    ToolCallFragment,
    TurnComplete,
)


class ReportModel:
    def __init__(self):
        self.prompts = []
        self.tools = []
        self.query_count = 0

    async def stream_chat(self, *, messages, tools=None, **kwargs):
        self.prompts.append(messages[0].content)
        self.tools.append({item["function"]["name"] for item in tools or []})
        last_user = max(index for index, turn in enumerate(messages) if turn.role == "user")
        current = messages[last_user:]
        tool_turns = [turn for turn in current if turn.role == "tool"]
        followup = "新增省份" in messages[last_user].content
        if not tool_turns and not followup:
            self.query_count += 1
            call = ToolCallFragment(
                id="q",
                name="query_db",
                arguments=json.dumps(
                    {
                        "sql": "SELECT date, region, province, amount, target FROM sales_target",
                    }
                ),
            )
        elif not tool_turns or (len(tool_turns) == 1 and not followup):
            design = (
                {"visible_columns": ["region", "province", "amount", "_share"], "chart_type": "bar"}
                if followup
                else {
                    "title": "DDI分析",
                    "dimension": "region",
                    "date_field": "date",
                    "metrics": {"amount": "amount", "target": "target"},
                    "filter_fields": ["region"],
                    "visible_columns": ["region", "amount", "target"],
                }
            )
            call = ToolCallFragment(
                id="r",
                name="render_report",
                arguments=json.dumps(
                    {
                        "reuse_previous": True,
                        "design": design,
                    }
                ),
            )
        else:
            yield TurnComplete(
                AssistantTurn(
                    content="交互报告已更新。", reasoning="", tool_calls=(), finish_reason="stop"
                )
            )
            return
        yield TurnComplete(
            AssistantTurn(
                content="",
                reasoning="按已核验数据生成报告。",
                tool_calls=(call,),
                finish_reason="tool_calls",
            )
        )

    async def aclose(self):
        pass


@pytest.mark.parametrize("mode", ["normal", "insight"])
def test_a_failed_report_edit_cannot_finish_as_if_it_were_saved(
    app,
    client,
    seed_user,
    auth_headers,
    monkeypatch,
    mode,
):
    def tool(name, arguments, call_id):
        return AssistantTurn(
            content="",
            reasoning="",
            tool_calls=(
                ToolCallFragment(
                    id=call_id,
                    name=name,
                    arguments=json.dumps(arguments),
                ),
            ),
            finish_reason="tool_calls",
        )

    class RepairModel:
        def __init__(self):
            self.repair_seen = False
            self.turns = [
                tool(
                    "query_db", {"sql": "SELECT '华东' AS region,80 AS amount,40 AS target"}, "q1"
                ),
                tool("render_report", {"design": {"visible_columns": ["unknown_field"]}}, "r1"),
                AssistantTurn(
                    content="假完成：报告已修改。",
                    reasoning="",
                    tool_calls=(),
                    finish_reason="stop",
                ),
                tool(
                    "render_report",
                    {
                        "design": {
                            "dimension": "region",
                            "metrics": {"amount": "amount", "target": "target"},
                        }
                    },
                    "r2",
                ),
                AssistantTurn(
                    content="已保存真实报告。", reasoning="", tool_calls=(), finish_reason="stop"
                ),
            ]

        async def stream_chat(self, *, messages, **kwargs):
            self.repair_seen |= any(
                "报告修改尚未保存" in turn.content for turn in messages if turn.role == "user"
            )
            yield TurnComplete(self.turns.pop(0))

        async def aclose(self):
            pass

    model = RepairModel()

    class Registry:
        def active_client(self):
            return model

    app.state.model_registry = Registry()
    sql_db = sqlite3.connect(":memory:", check_same_thread=False)

    def execute(sql, limit):
        cursor = sql_db.execute(sql)
        return [column[0] for column in cursor.description], cursor.fetchall(), False, 1

    monkeypatch.setattr(container, "_agent_query_fn", lambda *args: execute)
    seed_user("repair-owner")
    headers = auth_headers("repair-owner")
    response = client.post(
        "/api/v2/chat",
        headers=headers,
        json={
            "question": "修改报告",
            "mode": mode,
            "report_context": {"intent": "revise_report"},
        },
    )
    run_id = response.json()["run_id"]
    assert model.repair_seen
    report = client.get(f"/api/v2/runs/{run_id}/report", headers=headers)
    assert report.status_code == 200
    assert report.json()["rows"][0]["amount"] == 80
    events = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()["items"]
    final = next(event for event in events if event["type"] == "agent.done")
    assert final["payload"]["answer"] == "已保存真实报告。"
    sql_db.close()


@pytest.mark.parametrize("mode", ["normal", "insight"])
def test_shared_loop_builds_revises_and_authorizes_report(
    app,
    client,
    seed_user,
    auth_headers,
    monkeypatch,
    mode,
):
    model = ReportModel()

    class Registry:
        def active_client(self):
            return model

    app.state.model_registry = Registry()
    sql_db = sqlite3.connect(":memory:", check_same_thread=False)
    sql_db.execute(
        "CREATE TABLE sales_target(date TEXT, region TEXT, province TEXT, amount REAL, target REAL)"
    )
    sql_db.executemany(
        "INSERT INTO sales_target VALUES(?,?,?,?,?)",
        [
            ("2026-09-01", "华东", "江苏", 80, 40),
            ("2026-09-01", "华南", "广东", 120, 160),
        ],
    )

    def execute(sql, limit):
        cursor = sql_db.execute(sql)
        return [column[0] for column in cursor.description], cursor.fetchmany(limit), False, 1

    monkeypatch.setattr(container, "_agent_query_fn", lambda *args: execute)
    seed_user("report-owner")
    headers = auth_headers("report-owner")
    first = client.post(
        "/api/v2/chat", headers=headers, json={"question": "生成DDI交互报告", "mode": mode}
    )
    assert first.status_code == 202, first.text
    run_id = first.json()["run_id"]
    initial = client.get(f"/api/v2/runs/{run_id}/report", headers=headers)
    assert initial.status_code == 200, initial.text
    first_report = initial.json()
    assert first_report["rows"][0]["amount"] == 80
    events = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()["items"]
    assert any(event["type"] == "report.ready" for event in events)
    assert not any(event["type"].startswith("insight.") for event in events)
    assert "DDI分析" in model.prompts[0] and "html模板" in model.prompts[0]
    assert "## 洞察模式" not in model.prompts[0]
    second = client.post(
        "/api/v2/chat",
        headers=headers,
        json={
            "question": "新增省份字段和销售占比，改为柱状图",
            "mode": mode,
            "session_id": first.json()["session_id"],
            "report_context": {
                "report_id": first_report["id"],
                "revision": 1,
                "filters": {"region": "华东"},
            },
        },
    )
    assert second.status_code == 202, second.text
    revised = client.get(f"/api/v2/runs/{second.json()['run_id']}/report", headers=headers).json()
    assert revised["id"] == first_report["id"] and revised["revision"] == 2
    assert revised["rows"] == first_report["rows"]
    assert revised["filters"] == {"region": "华东"}
    assert revised["visible_columns"][-1] == "_share"
    assert model.query_count == 1
    assert all(names == model.tools[0] for names in model.tools)
    seed_user("other-report-user")
    assert client.get(
        f"/api/v2/runs/{run_id}/report", headers=auth_headers("other-report-user")
    ).status_code in (403, 404)
    assert client.get(f"/api/v2/runs/{run_id}/report").status_code == 401
    sql_db.close()


def test_clarification_resume_sends_one_tool_reply_per_call(
    app,
    client,
    seed_user,
    auth_headers,
):
    class StrictModel:
        replies = []

        async def stream_chat(self, *, messages, **kwargs):
            replies = [
                turn
                for turn in messages
                if turn.role == "tool" and turn.tool_call_id == "clarify-1"
            ]
            if not replies:
                call = ToolCallFragment(
                    id="clarify-1",
                    name="ask_user",
                    arguments=json.dumps(
                        {
                            "question": "选择业务范围",
                            "options": ["华东", "华南"],
                        }
                    ),
                )
                yield TurnComplete(
                    AssistantTurn(
                        content="",
                        reasoning="需要确定业务范围。",
                        tool_calls=(call,),
                        finish_reason="tool_calls",
                    )
                )
            else:
                self.replies = replies
                assert len(replies) == 1
                assert "华东" in replies[0].content
                yield TurnComplete(
                    AssistantTurn(
                        content="已按华东继续分析。",
                        reasoning="",
                        tool_calls=(),
                        finish_reason="stop",
                    )
                )

        async def aclose(self):
            pass

    model = StrictModel()

    class Registry:
        def active_client(self):
            return model

    app.state.model_registry = Registry()
    seed_user("resume-report-owner")
    headers = auth_headers("resume-report-owner")
    first = client.post(
        "/api/v2/chat", headers=headers, json={"question": "分析销售表现", "mode": "insight"}
    )
    run_id = first.json()["run_id"]
    cases = client.get("/api/v2/clarifications/waiting", headers=headers).json()
    case = next(case for case in cases if case["run_id"] == run_id)
    response = client.post(
        f"/api/v2/clarifications/{case['case_id']}/answers",
        headers=headers,
        json={"answers": [{"question_id": case["groups"][0]["question_id"], "free_text": "华东"}]},
    )
    assert response.status_code == 202
    assert client.get(f"/api/v2/runs/{run_id}", headers=headers).json()["status"] == "completed"
    assert len(model.replies) == 1
