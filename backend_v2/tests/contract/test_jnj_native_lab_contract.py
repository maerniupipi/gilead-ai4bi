"""J&J native SSE must resolve to its exact successful step-16 evidence."""

import asyncio
import json

import httpx
import pytest

from xiaoying_quick.infrastructure.lab_http.bootcamp import BootcampLabAdapter, BootcampLabConfig
from xiaoying_quick.infrastructure.lab_http.errors import LabHttpError
from xiaoying_quick.infrastructure.source_db.local_catalog import LocalSourceError
from xiaoying_quick.modules.labs import LabRequest

TRACE = "00000000-0000-0000-0000-000000000001"
QUERY = "按地区查询模拟业务金额"
SQL = "SELECT region, SUM(sales_amt) AS amount FROM sales_target_ai4bi GROUP BY region"


def fixture_trace():
    return {
        "trace_id": TRACE,
        "user_message": QUERY,
        "project_id": "999",
        "steps": [
            {
                "step_id": 16,
                "status": "done",
                "request": {"sql": SQL},
                "response": {
                    "columns": ["region", "amount"],
                    "rows": [{"region": "华北", "amount": 123}],
                    "row_count": 1,
                },
            },
            {"step_id": 17, "response": {"content": "UNTRUSTED PROSE 999999"}},
        ],
    }


def run(trace=None, events=None, authorization=""):
    seen = []
    trace = trace if trace is not None else fixture_trace()
    events = (
        events
        if events is not None
        else [
            {"type": "trace_id", "trace_id": TRACE},
            {"type": "summary", "delta": "UNTRUSTED"},
            {"type": "done"},
        ]
    )

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                content="".join("data: " + json.dumps(e) + "\n\n" for e in events),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json={"code": 200, "data": trace})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            adapter = BootcampLabAdapter(
                BootcampLabConfig(
                    endpoint_url="http://platform.test/api/autobi/gateway/v2/lab",
                    authorization=authorization,
                    lab_ids={"actual": "GILEADTEST"},
                    allow_insecure_http=True,
                ),
                client=client,
            )
            candidates = await adapter.generate_sql(
                LabRequest(atom_id="a", lab_id="actual", query=QUERY)
            )
            assert candidates[0].sql == SQL
            assert candidates[0].session_id == TRACE
            assert "UNTRUSTED" not in repr(candidates)
            assert adapter.execute(SQL, 10)[1] == (("华北", 123),)
            with pytest.raises(LocalSourceError):
                adapter.execute(SQL + " LIMIT 1", 10)
            restored = BootcampLabAdapter(adapter._bootcamp_config, client=client)
            restored.restore_evidence(adapter.dump_evidence())
            assert restored.execute(SQL, 10)[1] == (("华北", 123),)
        return seen

    return asyncio.run(exercise())


def test_native_contract_uses_matching_trace_and_executed_sql():
    seen = run()
    assert len(seen) == 2
    assert json.loads(seen[0].content)["id"] == "GILEADTEST"
    assert seen[1].url.path == "/api/autobi/lab/traces/" + TRACE
    assert "Authorization" not in seen[0].headers


@pytest.mark.parametrize("authorization", ["test-token", "Bearer test-token"])
def test_native_authorization_is_applied_to_stream_and_matching_trace(authorization):
    seen = run(authorization=authorization)
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in seen)


@pytest.mark.parametrize(
    "case", ["wrong_question", "wrong_trace", "query_error", "skipped", "missing_query", "bad_rows"]
)
def test_native_trace_failures_do_not_become_facts(case):
    trace = fixture_trace()
    if case == "wrong_question":
        trace["user_message"] = "another question"
    if case == "wrong_trace":
        trace["trace_id"] = "00000000-0000-0000-0000-000000000002"
    if case == "query_error":
        trace["steps"][0]["response"]["error"] = "private DB error"
    if case == "skipped":
        trace["steps"][0]["response"]["skipped"] = True
    if case == "missing_query":
        trace["steps"] = []
    if case == "bad_rows":
        trace["steps"][0]["response"]["rows"] = [[1, 2, 3]]
    with pytest.raises(LabHttpError) as failure:
        run(trace)
    assert "private DB error" not in str(failure.value)


def test_native_incomplete_or_failed_stream_is_rejected():
    for events in [
        [{"type": "trace_id", "trace_id": TRACE}],
        [{"type": "trace_id", "trace_id": TRACE}, {"type": "error"}, {"type": "done"}],
    ]:
        with pytest.raises(LabHttpError):
            run(events=events)
