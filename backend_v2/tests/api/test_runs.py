"""Run ownership, idempotency, cursor, and SSE API tests."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.infrastructure.result_xlsx import parse_result_xlsx_meta
from xiaoying_quick.modules.identity.contracts import Role, UserRecord
from xiaoying_quick.modules.runs.contracts import RunStatus
from xiaoying_quick.modules.runs.service import RunService


def test_report_context_resolves_the_selected_version_only_inside_its_session(
    client,
    app,
    seed_user,
    auth_headers,
):
    seed_user("report-editor")
    headers = auth_headers("report-editor")
    ids = []
    for session_id in ("owned-session", "another-session"):
        response = client.post(
            "/api/v2/runs", json={"question": "报告", "session_id": session_id}, headers=headers
        )
        ids.append(response.json()["run"]["id"])
    with session_scope(app.state.session_factory) as db:
        artifacts = SqlAlchemyArtifactRepository(db)
        for revision in (1, 2):
            artifacts.append(
                run_id=ids[0],
                kind="bi_report",
                payload={"id": "selected-report", "revision": revision},
            )
        artifacts.append(
            run_id=ids[1], kind="bi_report", payload={"id": "foreign-report", "revision": 1}
        )
        assert (
            artifacts.report_for_session(
                session_id="owned-session", report_id="selected-report", revision=1
            )["revision"]
            == 1
        )
        assert (
            artifacts.report_for_session(session_id="owned-session", report_id="selected-report")[
                "revision"
            ]
            == 2
        )
        assert (
            artifacts.report_for_session(session_id="owned-session", report_id="foreign-report")
            is None
        )


def _create_run(
    client: TestClient,
    headers: dict[str, str],
    *,
    question: str = "今年销量是多少？",
    key: str = "request-001",
) -> tuple[int, dict]:
    response = client.post(
        "/api/v2/runs",
        json={"question": question, "session_id": "session-1"},
        headers={**headers, "Idempotency-Key": key},
    )
    return response.status_code, response.json()


def test_run_creation_is_idempotent_and_creates_first_event(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")

    first_status, first = _create_run(client, headers)
    second_status, second = _create_run(client, headers)

    assert first_status == 201
    assert second_status == 200
    assert first["created"] is True
    assert second["created"] is False
    assert first["run"]["id"] == second["run"]["id"]
    assert first["run"]["next_event_cursor"] == 1

    events = client.get(f"/api/v2/runs/{first['run']['id']}/events", headers=headers)
    assert events.status_code == 200
    assert events.json()["items"] == [
        {
            "run_id": first["run"]["id"],
            "cursor": 1,
            "type": "run.created",
            "payload": {"status": "received", "session_id": "session-1"},
            "created_at": events.json()["items"][0]["created_at"],
        }
    ]


def test_idempotency_key_cannot_be_reused_for_different_payload(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    assert _create_run(client, headers)[0] == 201

    status_code, payload = _create_run(client, headers, question="另一个问题")
    assert status_code == 409
    assert payload["error"]["code"] == "CONFLICT"


def test_chat_retry_without_session_id_reuses_run_session_and_message(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("chat-user")
    headers = {
        **auth_headers("chat-user"),
        "Idempotency-Key": "chat-request-001",
    }

    first = client.post(
        "/api/v2/chat",
        json={"question": "今年销量是多少？"},
        headers=headers,
    )
    second = client.post(
        "/api/v2/chat",
        json={"question": "今年销量是多少？"},
        headers=headers,
    )

    assert first.status_code == 202, first.text
    assert second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["session_id"] == second.json()["session_id"]
    assert second.json()["created"] is False

    sessions = client.get("/api/v2/chat/sessions", headers=headers)
    messages = client.get(
        f"/api/v2/chat/sessions/{first.json()['session_id']}/messages",
        headers=headers,
    )
    assert len(sessions.json()) == 1
    assert [item["role"] for item in messages.json()].count("user") == 1


def test_chat_and_low_level_run_idempotency_namespaces_do_not_collide(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("namespace-user")
    headers = {
        **auth_headers("namespace-user"),
        "Idempotency-Key": "shared-key",
    }
    run = client.post(
        "/api/v2/runs",
        json={"question": "底层运行", "session_id": "manual-session"},
        headers=headers,
    )
    chat = client.post(
        "/api/v2/chat",
        json={"question": "聊天运行"},
        headers=headers,
    )

    assert run.status_code == 201, run.text
    assert chat.status_code == 202, chat.text
    assert run.json()["run"]["id"] != chat.json()["run_id"]


def test_run_access_is_owner_scoped_while_admin_can_read(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("owner")
    seed_user("other")
    seed_user("admin", role=Role.ADMIN)
    _, created = _create_run(client, auth_headers("owner"))
    run_id = created["run"]["id"]

    denied = client.get(f"/api/v2/runs/{run_id}", headers=auth_headers("other"))
    assert denied.status_code == 403

    allowed = client.get(f"/api/v2/runs/{run_id}", headers=auth_headers("admin"))
    assert allowed.status_code == 200
    assert allowed.json()["id"] == run_id


def test_events_are_append_only_monotonic_and_cursor_pageable(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    _, created = _create_run(client, headers)
    run_id = created["run"]["id"]

    with session_scope(app.state.session_factory) as session:
        service = RunService(SqlAlchemyRunRepository(session))
        service.transition(run_id=run_id, target=RunStatus.RUNNING)
        service.append_event(run_id=run_id, event_type="context.started", payload={"level": "L0"})

    page = client.get(f"/api/v2/runs/{run_id}/events?after=1&limit=1", headers=headers)
    assert page.status_code == 200
    assert [item["cursor"] for item in page.json()["items"]] == [2]
    assert page.json()["next_cursor"] == 2
    assert page.json()["has_more"] is True

    tail = client.get(f"/api/v2/runs/{run_id}/events?after=2", headers=headers)
    assert [item["cursor"] for item in tail.json()["items"]] == [3]
    assert not hasattr(SqlAlchemyRunRepository, "update_event")
    assert not hasattr(SqlAlchemyRunRepository, "delete_event")


def test_sse_snapshot_resumes_after_cursor(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    _, created = _create_run(client, headers)
    run_id = created["run"]["id"]

    response = client.get(
        f"/api/v2/runs/{run_id}/stream?follow=false",
        headers={**headers, "Last-Event-ID": "0"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 1\n" in response.text
    assert "event: run.created\n" in response.text

    empty = client.get(
        f"/api/v2/runs/{run_id}/stream?follow=false",
        headers={**headers, "Last-Event-ID": "1"},
    )
    assert empty.status_code == 200
    assert empty.text == ""


def test_trace_is_owner_scoped_and_redacts_sensitive_artifact_fields(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("owner")
    seed_user("other")
    seed_user("admin", role=Role.ADMIN)
    _, created = _create_run(client, auth_headers("owner"))
    run_id = created["run"]["id"]
    with session_scope(app.state.session_factory) as session:
        SqlAlchemyArtifactRepository(session).append(
            run_id=run_id,
            kind="lab_candidate",
            payload={
                "query": "今年销量",
                "sql": "SELECT 1",
                "token": "must-not-leak",
                "nested": {"secret_ref": "secret:123"},
                "scope_fingerprint": "scope-secret",
                "allowed_organizations": ["SECRET-ORG"],
                "allowed_regions": ["SECRET-REGION"],
            },
        )

    denied = client.get(
        f"/api/v2/runs/{run_id}/trace",
        headers=auth_headers("other"),
    )
    assert denied.status_code == 403

    owner = client.get(
        f"/api/v2/runs/{run_id}/trace",
        headers=auth_headers("owner"),
    )
    assert owner.status_code == 200
    body = owner.json()
    assert body["run"]["id"] == run_id
    assert body["artifacts"][0]["payload"] == {
        "query": "今年销量",
        "sql": "[REDACTED]",
        "token": "[REDACTED]",
        "nested": {"secret_ref": "[REDACTED]"},
        "scope_fingerprint": "[REDACTED]",
        "allowed_organizations": "[REDACTED]",
        "allowed_regions": "[REDACTED]",
    }
    assert body["evidence"] == []
    assert body["facts"] == []

    allowed = client.get(
        f"/api/v2/runs/{run_id}/trace",
        headers=auth_headers("admin"),
    )
    assert allowed.status_code == 200


def _store_export(app: FastAPI, run_id: str) -> str:
    with session_scope(app.state.session_factory) as session:
        return SqlAlchemyArtifactRepository(session).append(
            run_id=run_id,
            kind="xlsx_export",
            payload={
                "filename": "泰瑞沙YTD.xlsx",
                "title": "泰瑞沙 2025 YTD 地区经理城市销售",
                "summary": "Actual 销售金额，2025 全年",
                "columns": ["地区经理", "城市", "Actual 销售金额"],
                "rows": [
                    ["Vacant", "成都市", 24_409_575],
                    ["万明飞", "济南市", 31_011_425],
                    ["于桐", "北京市", 31_050_675],
                ],
                "row_count": 3,
            },
        )


def test_owner_can_download_xlsx_export(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    _, created = _create_run(client, headers)
    run_id = created["run"]["id"]
    export_id = _store_export(app, run_id)

    response = client.get(f"/api/v2/runs/{run_id}/exports/{export_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert "spreadsheetml.sheet" in response.headers["content-type"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    meta = parse_result_xlsx_meta(response.content)
    assert meta["row_count"] == 3
    assert "泰瑞沙 2025 YTD" in meta["banner"]
    assert meta["headers"] == ["地区经理", "城市", "Actual 销售金额"]
    assert meta["has_plum"] is True


def test_xlsx_export_download_is_owner_scoped(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("owner")
    seed_user("other")
    _, created = _create_run(client, auth_headers("owner"))
    run_id = created["run"]["id"]
    export_id = _store_export(app, run_id)

    denied = client.get(
        f"/api/v2/runs/{run_id}/exports/{export_id}",
        headers=auth_headers("other"),
    )
    assert denied.status_code == 403

    missing = client.get(
        f"/api/v2/runs/{run_id}/exports/artifact_missing",
        headers=auth_headers("owner"),
    )
    assert missing.status_code == 404
