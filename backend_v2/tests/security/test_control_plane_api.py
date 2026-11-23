"""Security properties enforced at the control-plane HTTP boundary."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xiaoying_quick.infrastructure.persistence.models.data_sources import AuditEventModel
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.modules.identity.contracts import Role, UserRecord
from xiaoying_quick.shared.ids import new_id


def test_audit_is_admin_only_and_defensively_redacts_metadata(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    admin = seed_user("admin", role=Role.ADMIN)
    seed_user("ordinary")
    secret = "raw-secret-that-must-not-be-returned"
    with session_scope(app.state.session_factory) as session:
        session.add(
            AuditEventModel(
                id=new_id("audit"),
                actor_id=admin.id,
                action="security.redaction_test",
                resource_id="resource-1",
                event_metadata={
                    "password": secret,
                    "nested": {"access_token": secret},
                    "message": f"postgresql://reader:{secret}@db.example/sales",
                },
            )
        )

    denied = client.get("/api/v2/admin/audit-events", headers=auth_headers("ordinary"))
    assert denied.status_code == 403

    response = client.get(
        "/api/v2/admin/audit-events?action=security.redaction_test",
        headers=auth_headers("admin"),
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert secret not in response.text
    assert response.json()[0]["metadata"]["password"] == "[REDACTED]"
    assert response.json()[0]["metadata"]["nested"]["access_token"] == "[REDACTED]"


def test_connection_url_credentials_are_rejected_without_echoing_them(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    embedded_secret = "url-password-never-echo"
    response = client.post(
        "/api/v2/admin/data-sources",
        json={
            "name": "unsafe",
            "connection_url": (
                f"postgresql+psycopg://reader:{embedded_secret}@db.example.test:5432"
            ),
            "username": "reader",
            "password": "separate-password",
            "selected_database": "sales",
            "dialect": "postgresql",
        },
        headers=auth_headers("admin"),
    )
    assert response.status_code == 422
    assert embedded_secret not in response.text
    assert "separate-password" not in response.text


def test_unapproved_or_secret_edited_knowledge_never_becomes_published(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    seed_user("alice")
    proposed = client.post(
        "/api/v2/knowledge/candidates",
        json={
            "scope": "business",
            "title": "业务口径",
            "content": "待审核业务规则",
            "rationale": "用户建议",
        },
        headers=auth_headers("alice"),
    )
    candidate_id = proposed.json()["id"]
    secret = "edited-secret-must-not-publish"

    approve = client.post(
        f"/api/v2/admin/knowledge/reviews/{candidate_id}/approve",
        json={"edited_content": f"password={secret}"},
        headers=auth_headers("admin"),
    )
    assert approve.status_code == 422
    assert secret not in approve.text

    published = client.get("/api/v2/knowledge/published", headers=auth_headers("alice"))
    assert published.status_code == 200
    assert published.json() == []
