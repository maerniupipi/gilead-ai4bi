"""Operational endpoint behavior and information-disclosure boundaries."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
)
from xiaoying_quick.modules.data_sources.contracts import (
    ConnectionTestResult,
    DataSourceRevision,
)
from xiaoying_quick.modules.health import (
    DependencyCheck,
    DependencyStatus,
    ReadinessService,
)
from xiaoying_quick.modules.labs import CandidateSQL, LabRequest


class _FailingProbe:
    def check(self) -> tuple[DependencyCheck, ...]:
        raise RuntimeError("postgresql://admin:super-secret@private.example/control")


class _NotReadyProbe:
    def check(self) -> tuple[DependencyCheck, ...]:
        return (
            DependencyCheck(
                name="application_database",
                status=DependencyStatus.ERROR,
                critical=True,
                mode="connectivity",
                detail="unreachable",
            ),
        )


class _ExplodingConnectionProbe:
    calls = 0

    def test(
        self,
        revision: DataSourceRevision,
        password: str | None,
    ) -> ConnectionTestResult:
        del revision, password
        self.calls += 1
        raise AssertionError("readiness connected to a business database")


class _ExplodingLab:
    calls = 0

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        del request
        self.calls += 1
        raise AssertionError("readiness called the laboratory")


def test_liveness_is_process_only_and_readiness_reports_passive_dependencies(
    client: TestClient,
) -> None:
    live = client.get("/api/v2/health/live")
    ready = client.get("/api/v2/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    payload = ready.json()
    assert payload["status"] == "ready"
    dependencies = {item["name"]: item for item in payload["dependencies"]}
    assert dependencies["application_database"]["status"] == "ok"
    assert dependencies["application_schema"]["status"] == "ok"
    assert dependencies["laboratory"] == {
        "name": "laboratory",
        "status": "not_configured",
        "critical": False,
        "mode": "passive_configuration",
        "detail": "network_probe_disabled",
    }
    assert dependencies["business_data_sources"]["mode"] == "control_metadata_only"


def test_readiness_is_503_when_a_critical_dependency_fails(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.readiness_service = ReadinessService(_NotReadyProbe())

    response = client.get("/api/v2/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_readiness_uses_configuration_only_for_external_dependencies(settings: Settings) -> None:
    engine = build_engine(settings.database_url)
    source_probe = _ExplodingConnectionProbe()
    lab = _ExplodingLab()
    application = create_app(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        connection_probe=source_probe,
        lab_port=lab,
    )

    with TestClient(application) as client:
        response = client.get("/api/v2/health/ready")

    assert response.status_code == 200
    dependencies = {item["name"]: item for item in response.json()["dependencies"]}
    assert dependencies["laboratory"]["status"] == "configured"
    assert dependencies["laboratory"]["mode"] == "passive_configuration"
    assert dependencies["business_data_sources"]["mode"] == "control_metadata_only"
    assert source_probe.calls == 0
    assert lab.calls == 0


def test_readiness_failure_does_not_disclose_probe_exception(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.readiness_service = ReadinessService(_FailingProbe())

    response = client.get("/api/v2/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"][0]["detail"] == "probe_failed"
    assert "super-secret" not in response.text
    assert "private.example" not in response.text
    assert client.get("/api/v2/health/live").status_code == 200
