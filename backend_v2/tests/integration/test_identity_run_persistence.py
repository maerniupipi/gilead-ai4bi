"""Identity and run state survive application/process reconstruction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings


def test_bootstrap_identity_and_run_events_survive_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "control-plane.sqlite3"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path}",
        db_auto_create=True,
        auth_hmac_secret=SecretStr("persistent-test-secret-with-at-least-32-bytes"),
        auth_issuer="persistence-test",
        bootstrap_admin_username="admin",
        bootstrap_admin_password=SecretStr("bootstrap-password"),
        sse_poll_seconds=0.05,
        sse_heartbeat_seconds=1.0,
    )

    with TestClient(create_app(settings=settings)) as first_client:
        token_response = first_client.post(
            "/api/v2/auth/token",
            json={"username": "admin", "password": "bootstrap-password"},
        )
        assert token_response.status_code == 200
        headers = {
            "Authorization": f"Bearer {token_response.json()['access_token']}",
            "Idempotency-Key": "restart-safe-request",
        }
        created = first_client.post(
            "/api/v2/runs",
            json={"question": "重启后还能恢复吗？"},
            headers=headers,
        )
        assert created.status_code == 201
        run_id = created.json()["run"]["id"]

    with TestClient(create_app(settings=settings)) as restarted_client:
        token_response = restarted_client.post(
            "/api/v2/auth/token",
            json={"username": "admin", "password": "bootstrap-password"},
        )
        assert token_response.status_code == 200
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

        recovered = restarted_client.get(f"/api/v2/runs/{run_id}", headers=headers)
        assert recovered.status_code == 200
        assert recovered.json()["question"] == "重启后还能恢复吗？"

        events = restarted_client.get(f"/api/v2/runs/{run_id}/events?after=0", headers=headers)
        assert events.status_code == 200
        assert [(event["cursor"], event["type"]) for event in events.json()["items"]] == [
            (1, "run.created")
        ]
