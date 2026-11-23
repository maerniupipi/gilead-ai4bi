"""Development lab fallback returns extractor-valid citations; production forbids mock."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr, ValidationError

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.lab_http.fallback import (
    FallbackLabPort,
    mock_lab_payload,
)
from xiaoying_quick.modules.labs import LabRequest, LabResponseExtractor


class _FailingLab:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    async def generate_sql(self, request: LabRequest) -> tuple[()]:
        self.calls += 1
        raise self.exc


def _request() -> LabRequest:
    return LabRequest(
        atom_id="atom-1",
        lab_id="actual",
        query="安达唐今年 YTD 金额达成率是多少？",
    )


def test_mock_payload_is_extractor_valid_and_keeps_the_atomic_query() -> None:
    request = _request()
    payload = mock_lab_payload(request)
    candidates = LabResponseExtractor().extract(
        payload, atom_id=request.atom_id, lab_id=request.lab_id
    )
    assert len(candidates) == 1
    assert candidates[0].query == request.query
    assert candidates[0].sql.upper().startswith("SELECT")


def test_fallback_port_uses_mock_when_the_real_lab_fails() -> None:
    inner = _FailingLab(TimeoutError("lab timeout"))
    port = FallbackLabPort(inner, on_error=True)
    candidates = asyncio.run(port.generate_sql(_request()))
    assert inner.calls == 1
    assert candidates[0].query == "安达唐今年 YTD 金额达成率是多少？"
    assert port.last_fallback == {
        "reason": "timeout",
        "fallback": True,
        "atom_id": "atom-1",
        "lab_id": "actual",
        "query": "安达唐今年 YTD 金额达成率是多少？",
    }


def test_fallback_port_mocks_when_no_lab_is_configured() -> None:
    port = FallbackLabPort(None, on_error=True)
    candidates = asyncio.run(port.generate_sql(_request()))
    assert candidates[0].query == "安达唐今年 YTD 金额达成率是多少？"
    assert port.last_fallback is not None
    assert port.last_fallback["reason"] == "unconfigured"


def test_fallback_can_be_disabled_so_errors_surface() -> None:
    port = FallbackLabPort(_FailingLab(RuntimeError("boom")), on_error=False)
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(port.generate_sql(_request()))
    assert port.last_fallback is None


def test_production_rejects_mock_fallback() -> None:
    with pytest.raises(ValidationError, match="laboratory mock fallback"):
        Settings(
            environment="production",
            database_url="postgresql://db.example/app",
            db_auto_create=False,
            allow_sqlite_data_sources=False,
            data_source_allowed_hosts=("db.example",),
            auth_hmac_secret=SecretStr("production-auth-secret-with-at-least-32-bytes"),
            sql_approval_hmac_secret=SecretStr("production-sql-secret-with-at-least-32-bytes"),
            master_key=SecretStr("configured-master-key"),
            lab_fallback="mock",
        )


def test_production_accepts_fallback_off() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql://db.example/app",
        db_auto_create=False,
        allow_sqlite_data_sources=False,
        data_source_allowed_hosts=("db.example",),
        auth_hmac_secret=SecretStr("production-auth-secret-with-at-least-32-bytes"),
        sql_approval_hmac_secret=SecretStr("production-sql-secret-with-at-least-32-bytes"),
        master_key=SecretStr("configured-master-key"),
        lab_fallback="off",
    )
    assert settings.lab_fallback == "off"
