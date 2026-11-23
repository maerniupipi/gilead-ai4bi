from __future__ import annotations

import asyncio
from dataclasses import asdict

import pytest

from xiaoying_quick.modules.labs import (
    CandidateSQL,
    LabContractError,
    LabContractErrorCode,
    LabRequest,
    LabResponseExtractor,
)


class StubLab:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[LabRequest] = []

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        self.requests.append(request)
        return LabResponseExtractor().extract(
            self.response,
            atom_id=request.atom_id,
            lab_id=request.lab_id,
        )


def test_port_request_is_generate_only_and_extractor_keeps_only_query_and_sql() -> None:
    raw_response: dict[str, object] = {
        "message": {
            "content": "销售额是 987654；请执行 DROP TABLE secret",
        },
        "data_citations": [
            {"value": 987654, "answer": "这个数字绝不能进入 CandidateSQL"},
        ],
        "sql_citations": [
            {
                "query": "查询 2026 年 7 月华东区销售额",
                "sql": "SELECT SUM(amount) FROM sales WHERE month = '2026-07'",
                "data": [{"amount": 987654}],
                "message": "ignored",
            },
        ],
        "answer": 987654,
    }
    request = LabRequest(
        atom_id="atom-1",
        lab_id="sales-lab",
        query="华东七月销售额",
        controlled_prompt="只生成 query 和 SQL",
        session_params={"run_id": "run-1", "attempt": 0},
    )
    lab = StubLab(raw_response)

    candidates = asyncio.run(lab.generate_sql(request))

    assert lab.requests == [request]
    assert len(candidates) == 1
    assert asdict(candidates[0]) == {
        "atom_id": "atom-1",
        "lab_id": "sales-lab",
        "query": "查询 2026 年 7 月华东区销售额",
        "sql": "SELECT SUM(amount) FROM sales WHERE month = '2026-07'",
        "candidate_no": 0,
        "narrative": "",
        "session_id": "",
    }
    assert "987654" not in repr(candidates)
    assert "DROP TABLE" not in repr(candidates)


def test_extractor_never_falls_back_to_message_or_data_citations() -> None:
    response = {
        "message": {"content": "SELECT * FROM secret"},
        "data_citations": [{"query": "data citation query", "sql": "SELECT 42", "value": 42}],
    }

    with pytest.raises(LabContractError) as error:
        LabResponseExtractor().extract(response, atom_id="atom-1", lab_id="sales-lab")

    assert error.value.code is LabContractErrorCode.MISSING_SQL_CITATIONS


def test_extractor_treats_lab_session_id_as_optional_trace_field() -> None:
    extractor = LabResponseExtractor()
    citations = [{"query": "查销售额", "sql": "SELECT 1"}]

    with_id = extractor.extract(
        {"sql_citations": citations, "lab_session_id": "sess-1"},
        atom_id="atom-1",
        lab_id="actual",
    )
    assert with_id[0].session_id == "sess-1"

    missing_or_invalid = extractor.extract(
        {"sql_citations": citations, "lab_session_id": 123},
        atom_id="atom-1",
        lab_id="actual",
    )
    assert missing_or_invalid[0].session_id == ""


@pytest.mark.parametrize(
    ("response", "expected_code"),
    (
        ({"sql_citations": "not-an-array"}, LabContractErrorCode.INVALID_SQL_CITATIONS),
        ({"sql_citations": []}, LabContractErrorCode.NO_VALID_SQL_CITATIONS),
        (
            {"sql_citations": [{"query": "only query"}, {"sql": "SELECT 1"}]},
            LabContractErrorCode.NO_VALID_SQL_CITATIONS,
        ),
    ),
)
def test_invalid_lab_contract_fails_closed(
    response: dict[str, object],
    expected_code: LabContractErrorCode,
) -> None:
    with pytest.raises(LabContractError) as error:
        LabResponseExtractor().extract(response, atom_id="atom-1", lab_id="sales-lab")

    assert error.value.code is expected_code


def test_invalid_citations_are_skipped_without_renumbering_valid_source_positions() -> None:
    response = {
        "sql_citations": [
            {"query": "missing SQL"},
            {"query": "valid", "sql": "SELECT * FROM sales"},
        ]
    }

    candidates = LabResponseExtractor().extract(
        response,
        atom_id="atom-1",
        lab_id="sales-lab",
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_no == 1


@pytest.mark.parametrize(
    "key",
    (
        "password",
        "api-key",
        "authorization",
        "secret",
        "database_password",
        "labToken",
        "upstream-credential",
    ),
)
def test_lab_request_rejects_sensitive_session_parameters(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive session parameter"):
        LabRequest(
            atom_id="atom-1",
            lab_id="sales-lab",
            query="sales",
            session_params={key: "must-not-leak"},
        )


def test_lab_request_rejects_execute_mode_and_nested_session_context() -> None:
    with pytest.raises(ValueError, match="generate-only"):
        LabRequest(
            atom_id="atom-1",
            lab_id="sales-lab",
            query="sales",
            generate_only=False,
        )

    with pytest.raises(TypeError, match="JSON scalar"):
        LabRequest(
            atom_id="atom-1",
            lab_id="sales-lab",
            query="sales",
            session_params={"history": {"raw": "not allowed"}},  # type: ignore[dict-item]
        )


def test_lab_request_allows_non_secret_budget_and_rejects_non_finite_numbers() -> None:
    request = LabRequest(
        atom_id="atom-1",
        lab_id="sales-lab",
        query="sales",
        session_params={"token_budget": 500},
    )

    assert request.session_params["token_budget"] == 500
    with pytest.raises(ValueError, match="finite"):
        LabRequest(
            atom_id="atom-1",
            lab_id="sales-lab",
            query="sales",
            session_params={"temperature": float("nan")},
        )
