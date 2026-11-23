from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from xiaoying_quick.application.lab_connection import LabConnectionService
from xiaoying_quick.bootstrap.lab_runtime import (
    LAB_CONNECTION_SNAPSHOT_KIND,
    resolve_run_lab_connection,
)
from xiaoying_quick.infrastructure.persistence.models import DataSourceModel, SourceLabModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunModel
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.shared.errors import ValidationFailed


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def put(self, value, *, current_ref=None):
        ref = current_ref or f"secret-{len(self.values) + 1}"
        self.values[ref] = value
        return ref

    def get(self, ref):
        return self.values[ref]

    def delete(self, ref):
        del self.values[ref]


def _bootcamp(*, mock=False, token="bootcamp-private-value", api_id="DEMOSALES1"):
    return {
        "active_provider": "bootcamp",
        "mock_enabled": mock,
        "profile": {
            "provider": "bootcamp",
            "endpoint_url": "http://127.0.0.1:8050/internal/lab/sql-evidence",
            "timeout_seconds": 91,
            "authorization": token,
            "user_id": 8,
            "space_id": 12,
            "labs": [{"lab_id": "actual", "api_access_id": api_id}],
        },
    }


def _bailian():
    return {
        "active_provider": "bailian",
        "mock_enabled": False,
        "profile": {
            "provider": "bailian",
            "endpoint_url": "https://bailian.example/opentrek-chat/v2/completions",
            "timeout_seconds": 42,
            "labs": [{"lab_id": "actual", "token": "bailian-private-value"}],
        },
    }


def _run(database, owner, run_id):
    database.add(
        RunModel(
            id=run_id,
            owner_user_id=owner.id,
            question="查询",
            status="received",
        )
    )
    database.flush()


@pytest.mark.parametrize("mock", [False, True])
def test_saved_run_keeps_provider_mapping_credentials_and_mock_after_global_switch(
    app,
    seed_user,
    mock,
):
    owner = seed_user("snapshot-owner")
    app.state.secret_store = MemorySecrets()
    with app.state.session_factory() as database:
        service = LabConnectionService(database, app.state.settings, app.state.secret_store)
        service.save(_bootcamp(mock=mock), actor_id=owner.id)
        _run(database, owner, "original")
        original = resolve_run_lab_connection(database, app, "original")
        service.save(
            _bootcamp(token="rotated-private-value", api_id="NEWLAB1234"), actor_id=owner.id
        )
        service.save(_bailian(), actor_id=owner.id)
        database.commit()

    with app.state.session_factory() as database:
        restored = resolve_run_lab_connection(database, app, "original")
        assert restored == original
        assert restored.provider == "bootcamp"
        assert restored.mock_enabled is mock
        assert restored.authorization == "bootcamp-private-value"
        assert restored.lab_credentials == {"actual": "DEMOSALES1"}
        assert (restored.timeout_seconds, restored.user_id, restored.space_id) == (91, 8, 12)
        repo = SqlAlchemyArtifactRepository(database)
        snapshot = repo.latest(run_id="original", kind=LAB_CONNECTION_SNAPSHOT_KIND)
        encoded = json.dumps(snapshot)
        assert "bootcamp-private-value" not in encoded
        assert "rotated-private-value" not in encoded
        assert "bailian-private-value" not in encoded
        assert "authorization_secret_ref" in snapshot
        assert len(repo.list_for_run("original")) == 1
        _run(database, owner, "new")
        assert resolve_run_lab_connection(database, app, "new").provider == "bailian"
        assert resolve_run_lab_connection(database, app).provider == "bailian"


def test_legacy_run_stays_legacy_when_workspace_first_configured(app, seed_user):
    owner = seed_user("legacy-owner")
    app.state.secret_store = MemorySecrets()
    with app.state.session_factory() as database:
        _run(database, owner, "legacy")
        before = resolve_run_lab_connection(database, app, "legacy")
        assert before.persisted is False
        LabConnectionService(database, app.state.settings, app.state.secret_store).save(
            _bootcamp(),
            actor_id=owner.id,
        )
        after = resolve_run_lab_connection(database, app, "legacy")
        assert after.provider == "bailian"
        assert after.mock_enabled is False
        assert after.persisted is False
        assert after.endpoint_url == before.endpoint_url
        snapshot = SqlAlchemyArtifactRepository(database).latest(
            run_id="legacy",
            kind=LAB_CONNECTION_SNAPSHOT_KIND,
        )
        assert snapshot == {"version": 1, "persisted": False}


def test_saved_bailian_run_pins_environment_tokens_as_secret_references(app, seed_user):
    owner = seed_user("environment-owner")
    app.state.secret_store = MemorySecrets()
    app.state.settings = app.state.settings.model_copy(
        update={"lab_actual_token": SecretStr("environment-private-value")},
    )
    with app.state.session_factory() as database:
        payload = _bailian()
        payload["profile"]["labs"] = []
        LabConnectionService(database, app.state.settings, app.state.secret_store).save(
            payload,
            actor_id=owner.id,
        )
        _run(database, owner, "environment")
        first = resolve_run_lab_connection(database, app, "environment")
        app.state.settings = app.state.settings.model_copy(
            update={"lab_actual_token": SecretStr("rotated-environment-value")},
        )
        restored = resolve_run_lab_connection(database, app, "environment")
        assert (
            restored.lab_credentials
            == first.lab_credentials
            == {
                "actual": "environment-private-value",
            }
        )
        snapshot = SqlAlchemyArtifactRepository(database).latest(
            run_id="environment",
            kind=LAB_CONNECTION_SNAPSHOT_KIND,
        )
        assert "environment-private-value" not in json.dumps(snapshot)
        assert "token_secret_ref" in snapshot["labs"]["actual"]


def test_mock_snapshot_cannot_resume_in_production(app, seed_user):
    owner = seed_user("production-owner")
    app.state.secret_store = MemorySecrets()
    with app.state.session_factory() as database:
        LabConnectionService(database, app.state.settings, app.state.secret_store).save(
            _bootcamp(mock=True),
            actor_id=owner.id,
        )
        _run(database, owner, "production")
        resolve_run_lab_connection(database, app, "production")
        app.state.settings = app.state.settings.model_copy(update={"environment": "production"})
        with pytest.raises(ValidationFailed, match="开发或测试"):
            resolve_run_lab_connection(database, app, "production")


def test_missing_source_secret_snapshots_effective_environment_fallback(app, seed_user):
    owner = seed_user("fallback-owner")
    app.state.secret_store = MemorySecrets()
    app.state.settings = app.state.settings.model_copy(
        update={"lab_actual_token": SecretStr("effective-environment-private-value")},
    )
    with app.state.session_factory() as database:
        database.add(
            DataSourceModel(
                id="missing-secret-source",
                name="Existing source",
                connection_url="sqlite://",
                selected_database="fixture",
                dialect="sqlite",
            )
        )
        database.flush()
        database.add(
            SourceLabModel(
                id="missing-secret-lab",
                data_source_id="missing-secret-source",
                lab_id="actual",
                name="Existing lab",
                token_secret_ref="missing-reference",
                created_by=owner.id,
            )
        )
        database.flush()
        payload = _bailian()
        payload["profile"]["labs"] = []
        LabConnectionService(database, app.state.settings, app.state.secret_store).save(
            payload,
            actor_id=owner.id,
        )
        _run(database, owner, "fallback")
        first = resolve_run_lab_connection(database, app, "fallback")
        assert first.lab_credentials == {"actual": "effective-environment-private-value"}
        database.commit()

    with app.state.session_factory() as database:
        restored = resolve_run_lab_connection(database, app, "fallback")
        assert restored == first
        snapshot = SqlAlchemyArtifactRepository(database).latest(
            run_id="fallback",
            kind=LAB_CONNECTION_SNAPSHOT_KIND,
        )
        ref = snapshot["labs"]["actual"]["token_secret_ref"]
        assert ref != "missing-reference"
        assert app.state.secret_store.get(ref) == "effective-environment-private-value"
        assert "effective-environment-private-value" not in json.dumps(snapshot)
