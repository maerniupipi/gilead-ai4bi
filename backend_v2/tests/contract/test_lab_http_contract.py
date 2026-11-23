from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine

import httpx
import pytest

from xiaoying_quick.infrastructure.lab_http import (
    HttpLabAdapter,
    LabHttpConfig,
    LabHttpError,
    LabHttpErrorCode,
)
from xiaoying_quick.modules.labs import (
    CandidateSQL,
    LabContractErrorCode,
    LabPort,
    LabRequest,
    supports_controlled_prompt,
)

_ACTUAL_TOKEN = "synthetic-actual-lab-token"
_DEMAND_TOKEN = "synthetic-demand-lab-token"
_RESPONSE_SECRET = "salary=987654; upstream-private-answer"
_CONTROLLED_PROMPT = "reserved-controlled-prompt-must-not-be-sent"
_ENDPOINT = "https://lab.example/opentrek-chat/v2/completions"


def _request(**overrides: object) -> LabRequest:
    values: dict[str, object] = {
        "atom_id": "atom-1",
        "lab_id": "actual",
        "query": "查询华东区 2026 年 7 月销售额",
        "controlled_prompt": _CONTROLLED_PROMPT,
        "session_params": {
            "max_sales_month": "2025-12",
            "run_id": "run-must-stay-local",
            "attempt": 0,
        },
    }
    values.update(overrides)
    return LabRequest(**values)  # type: ignore[arg-type]


def _config(**overrides: object) -> LabHttpConfig:
    values: dict[str, object] = {
        "endpoint_url": _ENDPOINT,
        "lab_tokens": {
            "actual": _ACTUAL_TOKEN,
            "demand": _DEMAND_TOKEN,
        },
        "timeout_seconds": 2.5,
    }
    values.update(overrides)
    return LabHttpConfig(**values)  # type: ignore[arg-type]


async def _invoke(port: LabPort, request: LabRequest) -> tuple[CandidateSQL, ...]:
    return await port.generate_sql(request)


def _run_with_transport(
    handler: (
        Callable[[httpx.Request], httpx.Response]
        | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
    ),
    *,
    config: LabHttpConfig | None = None,
    request: LabRequest | None = None,
    logger: logging.Logger | None = None,
    request_id: str = "lab-request-123",
) -> tuple[CandidateSQL, ...]:
    async def run() -> tuple[CandidateSQL, ...]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = HttpLabAdapter(
                config or _config(),
                client=client,
                logger=logger,
                request_id_factory=lambda: request_id,
            )
            return await _invoke(adapter, request or _request())

    return asyncio.run(run())


def _assert_no_leak(
    error: LabHttpError,
    *,
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    public_error = f"{error!s} {error!r}"
    records = [record for record in caplog.records if record.name == logger.name]
    assert records
    rendered_records = "\n".join(f"{record.getMessage()} {record.__dict__!r}" for record in records)
    for secret in (_ACTUAL_TOKEN, _DEMAND_TOKEN, _RESPONSE_SECRET):
        assert secret not in public_error
        assert secret not in rendered_records


def test_http_adapter_matches_documented_request_and_nested_response_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL(_ENDPOINT)
        assert request.headers["authorization"] == f"Bearer {_ACTUAL_TOKEN}"
        assert request.headers["x-request-id"] == "lab-request-123"
        assert request.extensions["timeout"] == {
            "connect": 2.5,
            "read": 2.5,
            "write": 2.5,
            "pool": 2.5,
        }

        request_body = json.loads(request.content)
        assert request_body == {
            "messages": [
                {
                    "role": "user",
                    "content": "查询华东区 2026 年 7 月销售额",
                }
            ],
            "stream": False,
            "features": {
                "max_sales_month": "2025-12",
                "loop_prompt_1": "",
                "loop_prompt_2": "",
                "loop_prompt_3": "",
                "loop_prompt_4": "",
                "loop_prompt_5": "",
            },
            "advanced_config": {},
        }
        serialized_body = request.content.decode()
        assert _CONTROLLED_PROMPT not in serialized_body
        assert "prompt_context" not in request_body
        assert "execute" not in request_body
        assert "session_params" not in request_body
        assert "run-must-stay-local" not in serialized_body

        return httpx.Response(
            200,
            json={
                "id": "6810ee369b9211f1934ec2599e2faa78",
                "status_code": "SUCCESS",
                "sql_citations": [{"query": "untrusted top-level", "sql": "DROP TABLE secret"}],
                "message": {
                    "role": "assistant",
                    "type": "statistics",
                    "content": "【理解】按 2026 年 7 月华东区汇总销售额。",
                    "features": {
                        "data_citations": [
                            {
                                "query": "data citation must be ignored",
                                "sql": "SELECT 987654",
                                "data": [{"amount": 987654}],
                            }
                        ],
                        "sql_citations": [
                            {
                                "query": "查询 2026 年 7 月华东区销售额",
                                "sql": "SELECT SUM(amount) FROM sales",
                                "rows": [{"amount": 987654}],
                            }
                        ],
                    },
                },
            },
        )

    candidates = _run_with_transport(handler)

    assert candidates == (
        CandidateSQL(
            atom_id="atom-1",
            lab_id="actual",
            query="查询 2026 年 7 月华东区销售额",
            sql="SELECT SUM(amount) FROM sales",
            candidate_no=0,
            narrative="【理解】按 2026 年 7 月华东区汇总销售额。",
            session_id="6810ee369b9211f1934ec2599e2faa78",
        ),
    )
    assert _RESPONSE_SECRET not in repr(candidates)
    assert "987654" not in repr(candidates)
    assert "DROP TABLE" not in repr(candidates)


def test_http_adapter_forwards_packed_loop_prompt_slots() -> None:
    packed = {
        "cur_sales_year": "2025",
        "cur_sales_month": "12",
        "max_sales_year": "2025",
        "max_sales_month": "12",
        "trty_code": "",
        "long_short_words": "None",
        "columns_value_knowledge": "「达成」默认金额 A/T%",
        "loop_prompt_1": "销量: 总计销售金额,sales_val",
        "loop_prompt_2": "该省=浙江",
        "loop_prompt_3": "【时间基准】数据最新月份为 2025 年 12 月。",
        "loop_prompt_4": "Actual：实际销售金额。",
        "loop_prompt_5": "",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        features = body["features"]
        for key, value in packed.items():
            assert features[key] == value
        # Session-local keys never leak into the outbound features body.
        assert "run_id" not in features
        return httpx.Response(
            200,
            json={
                "status_code": "SUCCESS",
                "message": {
                    "role": "assistant",
                    "type": "statistics",
                    "content": "ok",
                    "features": {"sql_citations": [{"query": "浙江开票销量", "sql": "SELECT 1"}]},
                },
            },
        )

    candidates = _run_with_transport(
        handler,
        request=_request(session_params={**packed, "run_id": "run-must-stay-local"}),
    )
    assert candidates[0].sql == "SELECT 1"


def test_http_adapter_explicitly_declares_no_controlled_prompt_capability() -> None:
    adapter = HttpLabAdapter(_config(), client=httpx.AsyncClient())

    assert supports_controlled_prompt(adapter) is False

    asyncio.run(adapter.aclose())


def test_adapter_selects_token_by_lab_id_without_putting_lab_id_in_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(_ENDPOINT)
        assert request.headers["authorization"] == f"Bearer {_DEMAND_TOKEN}"
        body = json.loads(request.content)
        assert "lab_id" not in body
        return httpx.Response(
            200,
            json={
                "message": {
                    "features": {
                        "sql_citations": [{"query": "需求查询", "sql": "SELECT * FROM demand"}]
                    }
                }
            },
        )

    candidates = _run_with_transport(
        handler,
        request=_request(lab_id="demand", session_params={}),
    )

    assert candidates[0].lab_id == "demand"


def test_config_requires_complete_https_endpoint_and_redacts_token_mapping() -> None:
    source_tokens = {"actual": _ACTUAL_TOKEN, "demand": _DEMAND_TOKEN}
    config = _config(lab_tokens=source_tokens)
    source_tokens["actual"] = "mutated-after-construction"

    assert _ACTUAL_TOKEN not in repr(config)
    assert _DEMAND_TOKEN not in repr(config)
    assert config.token_for("actual") == _ACTUAL_TOKEN
    with pytest.raises(ValueError, match="HTTPS"):
        _config(endpoint_url="http://lab.example/opentrek-chat/v2/completions")
    with pytest.raises(ValueError, match="credentials"):
        _config(endpoint_url=("https://user:password@lab.example/opentrek-chat/v2/completions"))
    with pytest.raises(ValueError, match="complete"):
        _config(endpoint_url="https://lab.example/api")


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    (
        (401, LabHttpErrorCode.HTTP_CLIENT_ERROR, False),
        (408, LabHttpErrorCode.TIMEOUT, True),
        (429, LabHttpErrorCode.RATE_LIMITED, True),
        (503, LabHttpErrorCode.HTTP_SERVER_ERROR, True),
        (307, LabHttpErrorCode.UNEXPECTED_STATUS, False),
    ),
)
def test_http_status_errors_are_classified_without_reading_or_leaking_body(
    status_code: int,
    expected_code: LabHttpErrorCode,
    retryable: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger(f"test.lab_http.status.{status_code}")
    caplog.set_level(logging.INFO, logger=logger.name)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            status_code,
            text=_RESPONSE_SECRET,
            headers={"Location": "https://untrusted.example/collect"},
        )

    with pytest.raises(LabHttpError) as caught:
        _run_with_transport(handler, logger=logger)

    error = caught.value
    assert error.code is expected_code
    assert error.status_code == status_code
    assert error.retryable is retryable
    assert error.request_id == "lab-request-123"
    _assert_no_leak(error, logger=logger, caplog=caplog)


def test_timeout_is_retryable_and_does_not_expose_transport_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.lab_http.timeout")
    caplog.set_level(logging.INFO, logger=logger.name)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(_RESPONSE_SECRET, request=request)

    with pytest.raises(LabHttpError) as caught:
        _run_with_transport(handler, logger=logger)

    error = caught.value
    assert error.code is LabHttpErrorCode.TIMEOUT
    assert error.status_code is None
    assert error.retryable
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_no_leak(error, logger=logger, caplog=caplog)


@pytest.mark.parametrize(
    ("response", "expected_code", "contract_code"),
    (
        (
            httpx.Response(200, content=b"not-json " + _RESPONSE_SECRET.encode()),
            LabHttpErrorCode.INVALID_JSON,
            None,
        ),
        (
            httpx.Response(200, json={"message": {"content": _RESPONSE_SECRET}}),
            LabHttpErrorCode.INVALID_RESPONSE,
            LabContractErrorCode.MISSING_SQL_CITATIONS,
        ),
        (
            httpx.Response(
                200,
                json={
                    "sql_citations": [{"query": "wrong path", "sql": "SELECT 987654"}],
                    "message": {
                        "content": _RESPONSE_SECRET,
                        "features": {
                            "data_citations": [
                                {
                                    "query": "wrong citation type",
                                    "sql": "SELECT 987654",
                                }
                            ]
                        },
                    },
                },
            ),
            LabHttpErrorCode.INVALID_RESPONSE,
            LabContractErrorCode.MISSING_SQL_CITATIONS,
        ),
    ),
)
def test_malformed_or_wrong_path_responses_fail_closed_without_leaking_body(
    response: httpx.Response,
    expected_code: LabHttpErrorCode,
    contract_code: LabContractErrorCode | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger(f"test.lab_http.malformed.{expected_code.value}")
    caplog.set_level(logging.INFO, logger=logger.name)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return response

    with pytest.raises(LabHttpError) as caught:
        _run_with_transport(handler, logger=logger)

    error = caught.value
    assert error.code is expected_code
    assert error.contract_code is contract_code
    assert not error.retryable
    _assert_no_leak(error, logger=logger, caplog=caplog)


def test_response_size_limit_fails_closed_without_echoing_partial_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=_RESPONSE_SECRET.encode())

    with pytest.raises(LabHttpError) as caught:
        _run_with_transport(handler, config=_config(max_response_bytes=8))

    assert caught.value.code is LabHttpErrorCode.RESPONSE_TOO_LARGE
    assert _RESPONSE_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "lab_request",
    (
        _request(lab_id="missing-lab"),
        _request(lab_id="../other-lab"),
        _request(session_params={"max_sales_month": 2025}),
    ),
)
def test_invalid_lab_or_feature_is_rejected_before_http(
    lab_request: LabRequest,
) -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del http_request
        calls += 1
        return httpx.Response(200, json={})

    with pytest.raises(LabHttpError) as caught:
        _run_with_transport(handler, request=lab_request)

    assert caught.value.code is LabHttpErrorCode.INVALID_REQUEST
    assert not caught.value.retryable
    assert calls == 0
