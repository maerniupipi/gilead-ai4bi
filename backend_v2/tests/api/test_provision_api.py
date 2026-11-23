"""HTTP provision endpoint creates schema and does not leak credentials."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from xiaoying_quick.infrastructure.persistence import bootstrap_runtime

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
)
from xiaoying_quick.modules.data_sources.contracts import ConnectionTestResult


class _PassingProbe:
    def test(self, revision: object, password: str | None) -> ConnectionTestResult:
        del revision, password
        return ConnectionTestResult(
            ok=True,
            latency_ms=1,
            database="AI_CVRM",
            server_version="8.0",
            read_only=True,
            errors=(),
        )


def _app(
    tmp_path: Path,
    *,
    target: str | None = None,
    connection_probe: object | None = None,
    **overrides: object,
) -> TestClient:
    database_url = target or f"sqlite:///{tmp_path / 'http-provision.sqlite'}"
    values: dict[str, object] = {
        "environment": "test",
        "database_url": database_url,
        "db_auto_create": True,
        "auth_hmac_secret": SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        "sql_approval_hmac_secret": SecretStr("test-sql-secret-with-at-least-32-bytes"),
        "secret_store_path": tmp_path / "secrets.json",
        "secret_key_path": tmp_path / "master.key",
        "knowledge_root": tmp_path / "knowledge",
        "data_source_allowed_hosts": ("db.example",),
    }
    values.update(overrides)
    settings = Settings(**values)  # type: ignore[arg-type]
    engine = build_engine("sqlite://")
    application = create_app(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        connection_probe=connection_probe,
    )
    return TestClient(application)


def test_provision_creates_configured_sqlite_schema(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        created = client.post("/api/v2/system/provision")
        status = client.get("/api/v2/system/database")

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["schema_applied"] is True
    assert "identity_users" in payload["tables"]
    assert payload["revision"]
    assert "password" not in created.text
    assert "appuser" not in created.text
    assert status.status_code == 200
    assert status.json()["action"] == "current"


def test_provision_token_is_required_when_configured(tmp_path: Path) -> None:
    with _app(tmp_path, provision_token=SecretStr("one-time-provision-token")) as client:
        missing = client.post("/api/v2/system/provision")
        wrong = client.post(
            "/api/v2/system/provision",
            headers={"X-Provision-Token": "nope"},
        )
        ok = client.post(
            "/api/v2/system/provision",
            headers={"X-Provision-Token": "one-time-provision-token"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200, ok.text
    assert "one-time-provision-token" not in ok.text


def test_import_sql_loads_script_with_provision_token(tmp_path: Path) -> None:
    token = "one-time-provision-token"
    with _app(tmp_path, provision_token=SecretStr(token)) as client:
        missing = client.post("/api/v2/system/import-sql", json={"sql": "SELECT 1"})
        uploaded = client.post(
            "/api/v2/system/import-sql",
            headers={"X-Provision-Token": token},
            files={
                "file": (
                    "02_AgentLoop.sql",
                    (
                        "SET NAMES utf8mb4;\n"
                        "CREATE TABLE IF NOT EXISTS import_probe "
                        "(id VARCHAR(8) PRIMARY KEY);\n"
                        "INSERT INTO import_probe (id) VALUES ('ok');\n"
                    ),
                    "application/sql",
                )
            },
        )

    assert missing.status_code == 401
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["imported"] is True
    assert body["executed"] == 2
    assert body["skipped"] == 1


def test_production_provision_requires_token(tmp_path: Path) -> None:
    from xiaoying_quick.infrastructure.persistence.provision import (
        provision_application_database,
    )

    boot_url = f"sqlite:///{tmp_path / 'boot.sqlite'}"
    provision_application_database(boot_url)
    engine = build_engine(boot_url)
    try:
        application = create_app(
            settings=Settings(
                environment="production",
                database_url=boot_url,
                db_auto_create=False,
                allow_sqlite_data_sources=False,
                data_source_allowed_hosts=("db.example",),
                master_key=SecretStr("production-master-key-for-secret-store"),
                auth_hmac_secret=SecretStr("production-auth-secret-with-at-least-32-bytes"),
                sql_approval_hmac_secret=SecretStr("production-sql-secret-with-at-least-32-bytes"),
                lab_fallback="off",
                secret_store_path=tmp_path / "secrets.json",
                secret_key_path=tmp_path / "master.key",
                knowledge_root=tmp_path / "knowledge",
            ),
            engine=engine,
            session_factory=build_session_factory(engine),
        )
        with TestClient(application) as client:
            response = client.post("/api/v2/system/provision")
    finally:
        engine.dispose()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_bootstrap_admin_creates_first_user_only(tmp_path: Path) -> None:
    with _app(tmp_path, provision_token=SecretStr("one-time-provision-token")) as client:
        denied = client.post(
            "/api/v2/system/bootstrap-admin",
            json={"username": "admin", "password": "test-admin-password"},
        )
        created = client.post(
            "/api/v2/system/bootstrap-admin",
            headers={"X-Provision-Token": "one-time-provision-token"},
            json={"username": "admin", "password": "test-admin-password"},
        )
        again = client.post(
            "/api/v2/system/bootstrap-admin",
            headers={"X-Provision-Token": "one-time-provision-token"},
            json={"username": "other", "password": "test-admin-password"},
        )
        login = client.post(
            "/api/v2/auth/token",
            json={"username": "admin", "password": "test-admin-password"},
        )

    assert denied.status_code == 401
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["username"] == "admin"
    assert payload["role"] == "admin"
    assert payload["created"] is True
    assert "password" not in created.text
    assert "test-admin-password" not in created.text
    assert again.status_code == 409
    assert login.status_code == 200, login.text
    assert login.json()["user"]["role"] == "admin"


def test_bootstrap_runtime_seeds_documented_source_and_lab_bindings(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap_runtime, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(bootstrap_runtime, "UAT_SOURCE_PASSWORD", "test-source-password")
    with _app(
        tmp_path,
        provision_token=SecretStr("one-time-provision-token"),
        connection_probe=_PassingProbe(),
    ) as client:
        created = client.post(
            "/api/v2/system/bootstrap-runtime",
            headers={"X-Provision-Token": "one-time-provision-token"},
        )
        again = client.post(
            "/api/v2/system/bootstrap-runtime",
            headers={"X-Provision-Token": "one-time-provision-token"},
        )
        login = client.post(
            "/api/v2/auth/token",
            json={"username": "admin", "password": "test-admin-password"},
        )
        sources = client.get(
            "/api/v2/admin/data-sources",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        bindings = client.get(
            "/api/v2/admin/domain-bindings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["admin_username"] == "admin"
    assert payload["data_source_name"] == "AI_CVRM 实验室查数库"
    assert payload["revision_id"]
    assert len(payload["bindings"]) == 4
    assert "test-source-password" not in created.text
    assert "password" not in created.text
    assert again.status_code == 200, again.text
    assert sources.status_code == 200, sources.text
    assert sources.json()[0]["selected_database"] == "AI_CVRM"
    assert sources.json()[0]["state"] == "active"
    active_domains = {item["domain_id"] for item in bindings.json() if item["active"]}
    assert active_domains == {"actual", "demand", "ext_simple", "ext_complex"}
