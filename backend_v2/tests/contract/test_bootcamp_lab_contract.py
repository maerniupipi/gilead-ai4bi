"""Bootcamp wire contract and fail-closed SQL execution evidence."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from xiaoying_quick.infrastructure.lab_http.bootcamp import BootcampLabAdapter, BootcampLabConfig
from xiaoying_quick.infrastructure.lab_http.errors import LabHttpError, LabHttpErrorCode
from xiaoying_quick.infrastructure.source_db.local_catalog import LocalSourceError
from xiaoying_quick.modules.labs import LabRequest


def config(**overrides):
    return BootcampLabConfig(
        **{
            "endpoint_url": "http://127.0.0.1:8050/internal/lab/sql-evidence",
            "authorization": "test-internal-secret",
            "lab_ids": {"actual": "DEMOSALES1"},
            "allow_insecure_http": True,
            "user_id": 7,
            "space_id": 9,
            **overrides,
        }
    )


def payload():
    return {
        "trace_id": "trace-123",
        "error": None,
        "sqls": [{"sql": "SELECT city, sales FROM demo_sales"}],
        "evidence": [
            {
                "sql": "SELECT city, sales FROM demo_sales",
                "columns": ["city", "sales"],
                "rows": [{"city": "上海", "sales": 42}, {"city": "北京", "sales": 80}],
                "row_count": 2,
            }
        ],
        "summary": "UNTRUSTED NARRATIVE",
        "steps": [{"private": "UNTRUSTED TRACE"}],
    }


def test_bootcamp_request_projection_and_cached_evidence():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload())

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BootcampLabAdapter(config(), client=client)
            candidates = await adapter.generate_sql(
                LabRequest(
                    atom_id="atom-1",
                    lab_id="actual",
                    query="按城市汇总销售",
                    controlled_prompt="DO NOT SEND HISTORY",
                    session_params={"cur_sales_year": "2026"},
                )
            )
            assert candidates[0].sql == "SELECT city, sales FROM demo_sales"
            assert candidates[0].session_id == "trace-123"
            assert candidates[0].narrative == ""
            assert "42" not in repr(candidates)
            assert adapter.execute(candidates[0].sql + ";", 1) == (
                ("city", "sales"),
                (("上海", 42),),
                True,
                0,
            )
            assert adapter.execute(candidates[0].sql, 10)[1] == (("上海", 42), ("北京", 80))
            with pytest.raises(LocalSourceError, match="平台执行证据"):
                adapter.execute("SELECT city, sales FROM demo_sales LIMIT 1", 10)
            isolated = BootcampLabAdapter(config(), client=client)
            with pytest.raises(LocalSourceError):
                isolated.execute(candidates[0].sql, 10)
            await adapter.aclose()
            with pytest.raises(LabHttpError) as error:
                await adapter.generate_sql(LabRequest(atom_id="x", lab_id="actual", query="x"))
            assert error.value.code == LabHttpErrorCode.CLOSED

    asyncio.run(exercise())
    request = seen[0]
    assert request.headers["X-Internal-Token"] == "test-internal-secret"
    assert request.headers["X-User-Id"] == "7"
    assert request.headers["X-Space-Id"] == "9"
    body = json.loads(request.content)
    assert body["id"] == "DEMOSALES1"
    assert body["content"] == "按城市汇总销售"
    assert body["features"]["cur_sales_year"] == "2026"
    assert "DO NOT SEND HISTORY" not in request.content.decode()
    assert "test-internal-secret" not in repr(config())


@pytest.mark.parametrize(
    "malform",
    [
        lambda data: data.update(error="secret backend failure"),
        lambda data: data.pop("evidence"),
        lambda data: data["evidence"][0].update(skipped=True),
        lambda data: data["evidence"][0].update(error="query failure"),
        lambda data: data["evidence"][0].update(columns=["city", "city"]),
        lambda data: data["evidence"][0].update(rows=[["上海"]]),
        lambda data: data["evidence"][0].update(rows=[{"city": "上海"}]),
        lambda data: data["evidence"][0].update(rows=[["上海", {"nested": "bad"}]]),
        lambda data: data["evidence"][0].update(row_count=0),
        lambda data: data["evidence"][0].update(sql="SELECT unrelated FROM private_table"),
    ],
)
def test_malformed_or_unexecuted_evidence_is_rejected(malform):
    data = payload()
    malform(data)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
        ) as client:
            adapter = BootcampLabAdapter(config(), client=client)
            with pytest.raises(LabHttpError) as error:
                await adapter.generate_sql(LabRequest(atom_id="a", lab_id="actual", query="q"))
            assert error.value.code == LabHttpErrorCode.INVALID_RESPONSE
            assert "secret" not in str(error.value)
            with pytest.raises(LocalSourceError):
                adapter.execute("SELECT city, sales FROM demo_sales", 20)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status,code",
    [
        (401, LabHttpErrorCode.HTTP_CLIENT_ERROR),
        (429, LabHttpErrorCode.RATE_LIMITED),
        (503, LabHttpErrorCode.HTTP_SERVER_ERROR),
        (302, LabHttpErrorCode.UNEXPECTED_STATUS),
    ],
)
def test_http_failures_are_sanitized_and_never_mocked(status, code):
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="secret and backend stack trace")
            )
        ) as client:
            adapter = BootcampLabAdapter(config(), client=client)
            with pytest.raises(LabHttpError) as error:
                await adapter.generate_sql(LabRequest(atom_id="a", lab_id="actual", query="q"))
            assert error.value.code == code
            assert "secret" not in str(error.value)

    asyncio.run(exercise())


def test_missing_mapping_and_oversized_responses_fail_closed():
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload()))
        ) as client:
            adapter = BootcampLabAdapter(config(max_response_bytes=10), client=client)
            with pytest.raises(LabHttpError) as error:
                await adapter.generate_sql(LabRequest(atom_id="a", lab_id="demand", query="q"))
            assert error.value.code == LabHttpErrorCode.INVALID_REQUEST
            with pytest.raises(LabHttpError) as error:
                await adapter.generate_sql(LabRequest(atom_id="a", lab_id="actual", query="q"))
            assert error.value.code == LabHttpErrorCode.RESPONSE_TOO_LARGE

    asyncio.run(exercise())


def test_run_evidence_restores_and_cross_lab_same_sql_stays_ambiguous():
    sql = "SELECT city, sales FROM demo_sales"

    def handler(request):
        data = payload()
        if json.loads(request.content)["id"] == "DEMODEMAND":
            data["evidence"][0]["rows"][0]["sales"] = 999
        return httpx.Response(200, json=data)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = config(lab_ids={"actual": "DEMOSALES1", "demand": "DEMODEMAND"})
            adapter = BootcampLabAdapter(settings, client=client)
            await adapter.generate_sql(LabRequest(atom_id="a", lab_id="actual", query="actual"))
            artifact = json.loads(json.dumps(adapter.dump_evidence()))
            resumed = BootcampLabAdapter(settings, client=client)
            resumed.restore_evidence(artifact)
            assert resumed.execute(sql, 20)[1][0] == ("上海", 42)
            await resumed.generate_sql(LabRequest(atom_id="b", lab_id="demand", query="demand"))
            with pytest.raises(LocalSourceError, match="多个实验室"):
                resumed.execute(sql, 20)
            conflicted = resumed.dump_evidence()
            assert conflicted[sql]["lab_ids"] == ["actual", "demand"]
            assert conflicted[sql]["rows"] == []
            third = BootcampLabAdapter(settings, client=client)
            third.restore_evidence(json.loads(json.dumps(conflicted)))
            with pytest.raises(LocalSourceError, match="多个实验室"):
                third.execute(sql, 20)
            malformed = json.loads(json.dumps(artifact))
            malformed[sql]["rows"] = [[42]]
            fresh = BootcampLabAdapter(settings, client=client)
            with pytest.raises(ValueError):
                fresh.restore_evidence(malformed)
            assert fresh.dump_evidence() == {}
            malicious = json.loads(json.dumps(artifact))
            malicious[sql]["lab_ids"] = ["unknown-lab"]
            with pytest.raises(ValueError):
                fresh.restore_evidence(malicious)
            assert fresh.dump_evidence() == {}

    asyncio.run(exercise())
