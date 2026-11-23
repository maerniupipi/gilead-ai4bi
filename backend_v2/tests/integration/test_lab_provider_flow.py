"""The real job/tool/export chain with deterministic model decisions and data."""

from __future__ import annotations

import asyncio
import io
import json
import re
import sqlite3
import zipfile

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from xiaoying_quick.bootstrap.container import build_agent_service
from xiaoying_quick.infrastructure.lab_http.bootcamp import BootcampLabAdapter, BootcampLabConfig
from xiaoying_quick.infrastructure.lab_http.demo import (
    DEMO_ROW_COUNT,
    DEMO_TABLES,
    DemoLabPort,
    ensure_demo_data,
    get_demo_gateway,
)
from xiaoying_quick.infrastructure.lab_http.errors import LabHttpError
from xiaoying_quick.infrastructure.llm.client import (
    AssistantTurn,
    ContentDelta,
    JsonCompletion,
    ToolCallFragment,
    TurnComplete,
)
from xiaoying_quick.infrastructure.source_db.local_catalog import LocalSourceError
from xiaoying_quick.modules.identity.contracts import Role
from xiaoying_quick.modules.labs import LabRequest


def _config(provider, *, mock=True):
    return {
        "active_provider": provider,
        "mock_enabled": mock,
        "profile": {
            "provider": provider,
            "endpoint_url": (
                "http://127.0.0.1:8050/internal/lab/sql-evidence"
                if provider == "bootcamp"
                else "https://bailian.example/opentrek-chat/v2/completions"
            ),
            "authorization": "demo-internal-secret",
            "labs": [
                {"lab_id": lab_id, "api_access_id": "DEMOSALES1", "token": f"demo-{lab_id}"}
                for lab_id in DEMO_TABLES
            ],
        },
    }


class WorkflowModel:
    """Controls decisions only; nested labs, queries, events and exports stay real."""

    async def stream_chat(self, *, purpose, messages, tools=None, max_tokens=None):
        tool_messages = [message for message in messages if message.role == "tool"]
        nested = purpose.startswith("nested.")
        if nested:
            if not tool_messages:
                name, args = "generate_sql", {"question": "2026年各地区销售额", "lab_id": "actual"}
            else:
                text = tool_messages[-1].content
                yield ContentDelta(text=text)
                yield TurnComplete(AssistantTurn(text, "", (), "stop"))
                return
        elif len(tool_messages) == 0:
            name, args = "agent_lab_sql", {"question": "2026年各地区销售额", "lab_id": "actual"}
        elif len(tool_messages) == 1:
            match = re.search(r"```sql\s*(.*?)```", tool_messages[0].content, flags=re.DOTALL)
            assert match, tool_messages[0].content
            name, args = "query_db", {"sql": match.group(1).strip()}
        elif len(tool_messages) == 2:
            assert "查询成功" in tool_messages[-1].content, tool_messages[-1].content
            name, args = "export_xlsx", {"title": "地区销售演示"}
        else:
            text = "演示数据：已完成各地区销售汇总，结果已导出。"
            yield ContentDelta(text=text)
            yield TurnComplete(AssistantTurn(text, "", (), "stop"))
            return
        call = ToolCallFragment(
            f"{'sub' if nested else 'main'}-{len(tool_messages)}", name, json.dumps(args)
        )
        yield TurnComplete(AssistantTurn("", "", (call,), "tool_calls"))

    async def complete_json(self, **kwargs):
        return JsonCompletion("review", {"ok": True, "uncertain": False, "missing": []})

    async def aclose(self):
        return None


class WorkflowRegistry:
    def active_client(self):
        return WorkflowModel()


class ClarifyingModel(WorkflowModel):
    async def stream_chat(self, *, purpose, messages, tools=None, max_tokens=None):
        tool_messages = [message for message in messages if message.role == "tool"]
        if not purpose.startswith("nested.") and len(tool_messages) == 1:
            call = ToolCallFragment(
                "clarify-export",
                "ask_user",
                json.dumps({"question": "是否导出当前汇总？", "options": ["导出", "不导出"]}),
            )
            yield TurnComplete(AssistantTurn("", "", (call,), "tool_calls"))
            return
        filtered = [message for message in messages if message.tool_call_id != "clarify-export"]
        async for event in super().stream_chat(purpose=purpose, messages=filtered, tools=tools):
            yield event


class ClarifyingRegistry:
    def active_client(self):
        return ClarifyingModel()


def _assert_chat_flow(app, client, headers, *, expected_mock, expected_rows=6):
    app.state.model_registry = WorkflowRegistry()
    response = client.post(
        "/api/v2/chat", json={"question": "2026年各地区销售额，并导出"}, headers=headers
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    run = client.get(f"/api/v2/runs/{run_id}", headers=headers).json()
    assert run["status"] == "completed", run
    page = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()
    events = page["items"]
    results = [
        {**event["payload"], **event["payload"].get("preview", {})}
        for event in events
        if event["type"] == "tool.result"
    ]
    query = next(item for item in results if item["name"] == "query_db")
    assert query["ok"] is True, query
    assert query["mock_enabled"] is expected_mock
    assert len(query["rows"]) == expected_rows
    assert query["sql_review"]["ok"] is True
    exported = next(item for item in results if item["name"] == "export_xlsx")
    assert exported["ok"] is True, exported
    download = client.get(exported["download_path"], headers=headers)
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
        assert "地区销售演示" in sheet or "sharedStrings" in workbook.namelist()
    stream = client.get(f"/api/v2/runs/{run_id}/stream", headers=headers)
    assert stream.status_code == 200
    assert "tool.result" in stream.text and "query_db" in stream.text
    assert "answer" in stream.text
    return query


@pytest.mark.parametrize("provider", ["bootcamp", "bailian"])
def test_mock_chat_nested_lab_query_trace_and_export(
    app, client, seed_user, auth_headers, provider
):
    seed_user("lab-admin", role=Role.ADMIN)
    headers = auth_headers("lab-admin")
    saved = client.put("/api/v2/admin/lab-connection", headers=headers, json=_config(provider))
    assert saved.status_code == 200, saved.text
    query = _assert_chat_flow(app, client, headers, expected_mock=True)
    assert query["lab_provider"] == provider
    assert "demo_actual" in query["sql"]
    assert {row[0] for row in query["rows"]} == {"华东", "华南", "华北", "华中", "西南", "西北"}


def test_bootcamp_chat_reads_platform_evidence_without_local_database(
    app,
    client,
    seed_user,
    auth_headers,
    monkeypatch,
):
    seed_user("lab-admin", role=Role.ADMIN)
    headers = auth_headers("lab-admin")
    saved = client.put(
        "/api/v2/admin/lab-connection", headers=headers, json=_config("bootcamp", mock=False)
    )
    assert saved.status_code == 200, saved.text
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "trace_id": "platform-trace",
                "sql": "SELECT region, SUM(amount) AS value FROM sales GROUP BY region",
                "sql_data": {
                    "columns": ["region", "value"],
                    "rows": [["华东", 100], ["华南", 200]],
                    "row_count": 2,
                },
            },
        )

    original = BootcampLabAdapter._generate_sql

    async def transport(self, request, unused_client):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as mock_client:
            return await original(self, request, mock_client)

    monkeypatch.setattr(BootcampLabAdapter, "_generate_sql", transport)
    query = _assert_chat_flow(app, client, headers, expected_mock=False, expected_rows=2)
    assert query["rows"] == [["华东", 100], ["华南", 200]]
    assert len(sent) == 1
    assert sent[0]["id"] == "DEMOSALES1"


def test_provider_switch_rebuilds_next_run_and_keeps_credentials(
    app, client, seed_user, auth_headers
):
    seed_user("lab-admin", role=Role.ADMIN)
    headers = auth_headers("lab-admin")
    for provider in ("bootcamp", "bailian", "bootcamp"):
        body = _config(provider)
        assert (
            client.put("/api/v2/admin/lab-connection", json=body, headers=headers).status_code
            == 200
        )
        with app.state.session_factory() as database:
            service = build_agent_service(database, app)
            assert service._tool_dependencies["lab"].provider == provider
            assert service._tool_dependencies["lab_provider"] == provider
            assert "演示数据" in service._system_prompt()
    stored = client.get("/api/v2/admin/lab-connection", headers=headers).json()
    assert all(lab["credential_configured"] for lab in stored["profiles"]["bailian"]["labs"])
    assert "demo-internal-secret" not in json.dumps(stored)


def test_large_demo_dataset_repeatability_and_read_only(tmp_path):
    path = ensure_demo_data(tmp_path / "demo.sqlite")
    with sqlite3.connect(path) as database:
        counts = [
            database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in DEMO_TABLES.values()
        ]
    assert sum(counts) == DEMO_ROW_COUNT
    assert len(set(counts)) == 1
    assert ensure_demo_data(path) == path
    gateway = get_demo_gateway(path)
    for lab_id in DEMO_TABLES:
        for question in (
            "2026年各地区销售额",
            "2025年各月销量",
            "2026年各产品达成率",
            "最新月市场份额",
        ):
            sql = asyncio.run(DemoLabPort().generate_sql(LabRequest("atom", lab_id, question)))[
                0
            ].sql
            _, rows, _, _ = gateway.execute(sql, 100)
            assert rows and all(row[-1] is not None for row in rows)
    with pytest.raises(OperationalError, match="readonly"):
        gateway.execute("DELETE FROM demo_actual", 10)
    _, rows, _, _ = gateway.execute("SELECT COUNT(*) FROM demo_actual", 1)
    assert rows[0][0] == counts[0]


def test_bootcamp_adapter_has_no_silent_mock_fallback():
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client:
            adapter = BootcampLabAdapter(
                BootcampLabConfig(
                    "https://platform.test/internal/lab/sql-evidence",
                    "test-token",
                    {"actual": "DEMOSALES1"},
                ),
                client=client,
            )
            with pytest.raises(LabHttpError):
                await adapter.generate_sql(LabRequest("atom", "actual", "销售额"))
            with pytest.raises(LocalSourceError, match="平台执行证据"):
                adapter.execute("SELECT 1", 10)

    asyncio.run(exercise())


def test_clarification_restores_bootcamp_evidence_after_global_platform_switch(
    app,
    client,
    seed_user,
    auth_headers,
    monkeypatch,
):
    seed_user("lab-admin", role=Role.ADMIN)
    headers = auth_headers("lab-admin")
    assert (
        client.put(
            "/api/v2/admin/lab-connection", headers=headers, json=_config("bootcamp", mock=False)
        ).status_code
        == 200
    )
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "sql": "SELECT region, SUM(amount) AS value FROM sales GROUP BY region",
                "sql_data": {
                    "columns": ["region", "value"],
                    "rows": [["华东", 12345]],
                    "row_count": 1,
                },
            },
        )

    original = BootcampLabAdapter._generate_sql

    async def transport(self, request, unused_client):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as mock_client:
            return await original(self, request, mock_client)

    monkeypatch.setattr(BootcampLabAdapter, "_generate_sql", transport)
    app.state.model_registry = ClarifyingRegistry()
    started = client.post("/api/v2/chat", headers=headers, json={"question": "2026年各地区销售额"})
    run_id = started.json()["run_id"]
    assert (
        client.get(f"/api/v2/runs/{run_id}", headers=headers).json()["status"]
        == "waiting_clarification"
    )
    waiting = client.get(
        "/api/v2/clarifications/waiting", params={"run_id": run_id}, headers=headers
    ).json()[0]
    group = waiting["groups"][0]
    assert (
        client.put(
            "/api/v2/admin/lab-connection", headers=headers, json=_config("bailian", mock=True)
        ).status_code
        == 200
    )
    resumed = client.post(
        f"/api/v2/clarifications/{waiting['case_id']}/answers",
        headers=headers,
        json={
            "answers": [
                {"question_id": group["question_id"], "choice_id": group["choices"][0]["id"]}
            ]
        },
    )
    assert resumed.status_code == 202, resumed.text
    assert client.get(f"/api/v2/runs/{run_id}", headers=headers).json()["status"] == "completed"
    events = client.get(f"/api/v2/runs/{run_id}/events", headers=headers).json()["items"]
    query = next(
        event["payload"]
        for event in events
        if event["type"] == "tool.result" and event["payload"]["name"] == "query_db"
    )
    assert query["ok"] is True, query
    assert query["preview"]["rows"] == [["华东", 12345]]
    assert query["preview"]["lab_provider"] == "bootcamp"
    assert query["preview"]["mock_enabled"] is False
    assert len(sent) == 1  # No regeneration, wrong-provider query, or local DB access after resume.
