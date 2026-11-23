from __future__ import annotations

import json

from xiaoying_quick.application.lab_connection import LabConnectionService
from xiaoying_quick.infrastructure.persistence.models.lab_connection import LabConnectionModel
from xiaoying_quick.modules.identity.contracts import Role
from xiaoying_quick.modules.labs import CandidateSQL

URL = "/api/v2/admin/lab-connection"


def bootcamp_body(**overrides):
    return {
        "active_provider": "bootcamp",
        "mock_enabled": False,
        "profile": {
            "provider": "bootcamp",
            "endpoint_url": "http://127.0.0.1:8050/internal/lab/sql-evidence",
            "timeout_seconds": 90,
            "authorization": "bootcamp-secret",
            "user_id": 1,
            "space_id": 7,
            "labs": [{"lab_id": "actual", "api_access_id": "DEMOSALES1"}],
        },
        **overrides,
    }


def test_admin_only_and_safe_default(client, seed_user, auth_headers):
    assert client.get(URL).status_code == 401
    seed_user("normal")
    assert client.get(URL, headers=auth_headers("normal")).status_code == 403
    seed_user("admin", role=Role.ADMIN)
    result = client.get(URL, headers=auth_headers("admin"))
    assert result.status_code == 200
    data = result.json()
    assert data["active_provider"] == "bailian"
    assert data["mock_enabled"] is False
    assert data["mock_available"] is True
    assert len(data["profiles"]["bootcamp"]["labs"]) == 4


def test_roundtrip_switch_and_blank_secrets_preserve_existing(
    client,
    app,
    seed_user,
    auth_headers,
):
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    saved = client.put(URL, headers=headers, json=bootcamp_body())
    assert saved.status_code == 200, saved.text
    assert saved.json()["profiles"]["bootcamp"]["token_configured"] is True
    assert "bootcamp-secret" not in saved.text
    blank = bootcamp_body()
    blank["profile"]["authorization"] = ""
    assert client.put(URL, headers=headers, json=blank).status_code == 200
    bailian = {
        "active_provider": "bailian",
        "mock_enabled": False,
        "profile": {
            "provider": "bailian",
            "endpoint_url": "https://lab.example/opentrek-chat/v2/completions",
            "timeout_seconds": 30,
            "labs": [{"lab_id": "actual", "token": "bailian-secret"}],
        },
    }
    saved = client.put(URL, headers=headers, json=bailian)
    assert saved.status_code == 200, saved.text
    assert "bailian-secret" not in saved.text
    bailian["profile"]["labs"][0]["token"] = ""
    assert client.put(URL, headers=headers, json=bailian).status_code == 200
    with app.state.session_factory() as session:
        service = LabConnectionService(session, app.state.settings, app.state.secret_store)
        assert service.has_saved_config()
        assert service.resolve().provider == "bailian"
        assert service.resolve().lab_credentials["actual"] == "bailian-secret"
        bootcamp = service.resolve("bootcamp")
        assert bootcamp.authorization == "bootcamp-secret"
        assert bootcamp.lab_credentials == {"actual": "DEMOSALES1"}
        stored = json.dumps(session.get(LabConnectionModel, "workspace").profiles)
        assert "bootcamp-secret" not in stored
        assert "bailian-secret" not in stored
    loaded = client.get(URL, headers=headers).json()
    assert loaded["profiles"]["bootcamp"]["labs"][0]["api_access_id"] == "DEMOSALES1"


def test_test_uses_unsaved_draft_and_does_not_save_or_leak(
    client,
    app,
    seed_user,
    auth_headers,
    monkeypatch,
):
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    seen = []

    async def generate(adapter, request):
        seen.append((adapter._bootcamp_config, request))
        return (
            CandidateSQL(
                atom_id=request.atom_id,
                lab_id=request.lab_id,
                query=request.query,
                sql="SELECT 1",
                candidate_no=0,
            ),
        )

    monkeypatch.setattr(
        "xiaoying_quick.api.routers.lab_connection.BootcampLabAdapter.generate_sql",
        generate,
    )
    result = client.post(URL + "/test", headers=headers, json=bootcamp_body())
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["candidate_count"] == 1
    assert seen[0][0].authorization == "bootcamp-secret"
    assert "bootcamp-secret" not in result.text
    with app.state.session_factory() as session:
        assert session.get(LabConnectionModel, "workspace") is None
    assert client.get(URL, headers=headers).json()["active_provider"] == "bailian"


def test_mock_explicit_and_production_disallowed(
    client,
    app,
    seed_user,
    auth_headers,
):
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    body = bootcamp_body(mock_enabled=True)
    result = client.post(URL + "/test", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["mock_enabled"] is True
    assert "演示" in result.json()["message"]
    assert (app.state.settings.secret_store_path.parent / "demo-labs-v1.sqlite").exists()
    app.state.settings = app.state.settings.model_copy(update={"environment": "production"})
    assert client.get(URL, headers=headers).json()["mock_available"] is False
    rejected = client.put(URL, headers=headers, json=body)
    assert rejected.status_code == 422
    assert "演示数据" in rejected.json()["error"]["message"]


def test_invalid_url_duplicate_lab_and_network_failure_do_not_mock(
    client,
    seed_user,
    auth_headers,
    monkeypatch,
):
    from xiaoying_quick.infrastructure.lab_http.errors import LabHttpError, LabHttpErrorCode

    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    body = bootcamp_body()
    body["profile"]["endpoint_url"] += "?token=sensitive"
    assert client.put(URL, headers=headers, json=body).status_code == 422
    body = bootcamp_body()
    body["profile"]["labs"] *= 2
    assert client.put(URL, headers=headers, json=body).status_code == 422

    async def unavailable(*args):
        raise LabHttpError(LabHttpErrorCode.NETWORK_ERROR, request_id="test", retryable=True)

    monkeypatch.setattr(
        "xiaoying_quick.api.routers.lab_connection.BootcampLabAdapter.generate_sql",
        unavailable,
    )
    result = client.post(URL + "/test", headers=headers, json=bootcamp_body())
    assert result.json()["ok"] is False
    assert result.json()["candidate_count"] == 0
    assert result.json()["mock_enabled"] is False
    assert "网络" in result.json()["message"]


def test_incomplete_live_profile_and_mismatched_provider_cannot_be_saved(
    client,
    app,
    seed_user,
    auth_headers,
):
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    bodies = []
    for field, value in (("endpoint_url", ""), ("authorization", ""), ("labs", [])):
        body = bootcamp_body()
        body["profile"][field] = value
        bodies.append(body)
    bodies.append(bootcamp_body(active_provider="bailian"))
    for body in bodies:
        result = client.put(URL, headers=headers, json=body)
        assert result.status_code == 422, result.text
    with app.state.session_factory() as session:
        assert session.get(LabConnectionModel, "workspace") is None


def test_missing_legacy_source_secret_does_not_block_bootcamp(
    client,
    app,
    seed_user,
    auth_headers,
):
    from xiaoying_quick.infrastructure.persistence.models import DataSourceModel, SourceLabModel

    admin = seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    with app.state.session_factory() as session:
        session.add(
            DataSourceModel(
                id="old-source",
                name="Old source",
                connection_url="sqlite://",
                selected_database="test",
                dialect="sqlite",
            )
        )
        session.flush()
        session.add(
            SourceLabModel(
                id="old-lab",
                data_source_id="old-source",
                lab_id="actual",
                name="Old lab",
                token_secret_ref="missing-reference",
                created_by=admin.id,
            )
        )
        session.commit()
    assert client.get(URL, headers=headers).status_code == 200
    result = client.put(URL, headers=headers, json=bootcamp_body())
    assert result.status_code == 200, result.text
    assert result.json()["active_provider"] == "bootcamp"


def test_production_refuses_persisted_mock_but_admin_can_turn_it_off(
    client,
    app,
    seed_user,
    auth_headers,
):
    import pytest

    from xiaoying_quick.shared.errors import ValidationFailed

    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    body = bootcamp_body(mock_enabled=True)
    assert client.put(URL, headers=headers, json=body).status_code == 200
    app.state.settings = app.state.settings.model_copy(update={"environment": "production"})
    with app.state.session_factory() as session:
        service = LabConnectionService(session, app.state.settings, app.state.secret_store)
        with pytest.raises(ValidationFailed, match="生产环境"):
            service.resolve()
    shown = client.get(URL, headers=headers)
    assert shown.status_code == 200
    assert shown.json()["mock_enabled"] is True
    assert shown.json()["mock_available"] is False
    body["mock_enabled"] = False
    body["profile"]["endpoint_url"] = "https://lab.example/internal/lab/sql-evidence"
    assert client.put(URL, headers=headers, json=body).status_code == 200
    with app.state.session_factory() as session:
        service = LabConnectionService(session, app.state.settings, app.state.secret_store)
        assert service.resolve().mock_enabled is False
