from __future__ import annotations

import asyncio
from types import TracebackType
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from xiaoying_quick.bootstrap import container
from xiaoying_quick.bootstrap.container import (
    ConfiguredHttpLabPort,
    LabUnavailableError,
    build_agent_service,
    build_lab_port,
    build_model_registry,
)
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.lab_http import LabHttpConfig
from xiaoying_quick.infrastructure.llm.registry import ModelRegistry
from xiaoying_quick.modules.agent import ToolRegistry
from xiaoying_quick.modules.labs import CandidateSQL, LabRequest


class StubLabPort:
    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        del request
        return ()


class StubSecretStore:
    def put(self, value: str, *, current_ref: str | None = None) -> str:
        del value, current_ref
        return "secret-ref"

    def get(self, secret_ref: str) -> str:
        del secret_ref
        return "database-password"

    def delete(self, secret_ref: str) -> None:
        del secret_ref


def test_agent_service_composition_wires_the_full_loop(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = StubLabPort()
    secrets = StubSecretStore()
    app.state.lab_port = lab
    app.state.secret_store = secrets

    with app.state.session_factory() as database:
        checkpoint = Mock(wraps=database.commit)
        monkeypatch.setattr(database, "commit", checkpoint)
        agent = build_agent_service(database, app)

        assert isinstance(agent._tools, ToolRegistry)
        assert set(agent._tools.names()) == {
            "query_db",
            "export_xlsx",
            "render_report",
            "knowledge_search",
            "knowledge_read",
            "memory_save",
            "ask_user",
            "update_ledger",
            "agent_lab_sql",
            "agent_bailian",
        }
        assert agent._tool_dependencies["local_source"] is not None
        assert agent._tool_dependencies["artifacts"] is not None
        assert isinstance(agent._model_registry, ModelRegistry)
        assert agent._tool_dependencies["lab"] is lab
        assert callable(agent._tool_dependencies["query_db"])
        assert callable(agent._tool_dependencies["bailian_recall"])
        assert agent._tool_dependencies["memory_writer"] is not None
        assert agent._tool_dependencies["knowledge_proposer"] is not None

        agent._checkpoint()
        checkpoint.assert_called_once_with()


def test_agent_query_db_fails_loudly_without_azai_credentials(
    app: FastAPI,
) -> None:
    """No AZAI config means the tool surfaces an error, never a silent no-op."""

    app.state.lab_port = StubLabPort()
    app.state.secret_store = StubSecretStore()

    with app.state.session_factory() as database:
        agent = build_agent_service(database, app)
        query_db = agent._tool_dependencies["query_db"]
        with pytest.raises(LabUnavailableError):
            query_db("SELECT 1", 10)


def test_agent_query_db_builds_the_azai_placeholder_revision(
    app: FastAPI,
) -> None:
    """With AZAI credentials the placeholder revision must construct cleanly.

    Regression: the runner ignores the revision, but building it used to miss
    mandatory dataclass fields and crashed every run with a TypeError.
    """

    app.state.lab_port = StubLabPort()
    app.state.secret_store = StubSecretStore()
    app.state.settings = app.state.settings.model_copy(
        update={
            "azai_create_session_url": "https://azai.test/createSession",
            "azai_run_url": "https://azai.test/run",
            "azai_agent_code": "agent-code",
            "azai_agent_version": "1",
            "azai_authorization": SecretStr("Bearer test-token"),
        }
    )

    with app.state.session_factory() as database:
        agent = build_agent_service(database, app)
        assert callable(agent._tool_dependencies["query_db"])


def test_model_registry_is_wired_against_the_request_transaction(
    app: FastAPI,
) -> None:
    app.state.secret_store = StubSecretStore()

    with app.state.session_factory() as database:
        registry = build_model_registry(database, app)
        assert isinstance(registry, ModelRegistry)
        assert registry.service().list_configs() == ()


def test_lab_port_prefers_app_state_and_fails_safely_when_unconfigured(
    app: FastAPI,
) -> None:
    injected = StubLabPort()
    app.state.lab_port = injected
    assert build_lab_port(app) is injected

    del app.state.lab_port
    unavailable = build_lab_port(app)
    from xiaoying_quick.infrastructure.lab_http.fallback import FallbackLabPort

    assert isinstance(unavailable, FallbackLabPort)
    request = LabRequest(
        atom_id="atom-1",
        lab_id="actual",
        query="private business question that must not be echoed",
    )
    candidates = asyncio.run(unavailable.generate_sql(request))
    assert candidates[0].query == request.query
    assert unavailable.last_fallback is not None
    assert "token" not in repr(unavailable).casefold()


def test_configured_lab_port_uses_four_secret_tokens_and_default_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = {
        "actual": "synthetic-actual-token-value",
        "demand": "synthetic-demand-token-value",
        "ext_simple": "synthetic-external-simple-token",
        "ext_complex": "synthetic-external-complex-token",
    }
    settings = Settings(
        environment="test",
        lab_endpoint_url="https://lab.example/opentrek-chat/v2/completions",
        lab_actual_token=SecretStr(tokens["actual"]),
        lab_demand_token=SecretStr(tokens["demand"]),
        lab_ext_simple_token=SecretStr(tokens["ext_simple"]),
        lab_ext_complex_token=SecretStr(tokens["ext_complex"]),
        lab_max_sales_month="2026-07",
        lab_fallback="off",
    )
    app = FastAPI()
    app.state.settings = settings
    port = build_lab_port(app)

    assert isinstance(port, ConfiguredHttpLabPort)
    assert all(secret not in repr(port) for secret in tokens.values())
    assert all(secret not in repr(settings) for secret in tokens.values())

    captured: list[LabRequest] = []

    class CapturingAdapter:
        def __init__(self, config: LabHttpConfig) -> None:
            self.config = config

        async def __aenter__(self) -> CapturingAdapter:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exc_type, exc_value, traceback

        async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
            captured.append(request)
            return ()

    monkeypatch.setattr(container, "HttpLabAdapter", CapturingAdapter)
    asyncio.run(
        port.generate_sql(
            LabRequest(
                atom_id="atom-1",
                lab_id="actual",
                query="sales",
                controlled_prompt="reserved but local",
                session_params={"run_id": "run-1"},
            )
        )
    )

    assert captured[0].session_params == {
        "run_id": "run-1",
    }
