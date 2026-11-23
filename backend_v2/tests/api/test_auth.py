"""Authentication and RBAC API tests."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from xiaoying_quick.modules.identity.contracts import Role, UserRecord


def test_health_is_available_without_authentication(client: TestClient) -> None:
    response = client.get("/api/v2/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_credentials_issue_token_and_me_uses_verified_identity(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    user = seed_user("赵琳", display_name="赵琳")
    response = client.get("/api/v2/auth/me", headers=auth_headers("赵琳"))

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "username": "赵琳",
        "display_name": "赵琳",
        "role": "user",
    }


def test_wrong_password_and_tampered_token_are_rejected(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    token_for: Callable[..., str],
) -> None:
    seed_user("alice")
    bad_password = client.post(
        "/api/v2/auth/token",
        json={"username": "alice", "password": "definitely-wrong"},
    )
    assert bad_password.status_code == 401
    assert bad_password.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    token = token_for("alice")
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    invalid = client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert invalid.status_code == 401
    assert invalid.headers["www-authenticate"] == "Bearer"


def test_only_admin_can_create_users(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    seed_user("ordinary")
    request = {
        "username": "reviewer",
        "password": "reviewer-password",
        "display_name": "Reviewer",
        "role": "knowledge_reviewer",
    }

    denied = client.post("/api/v2/auth/users", json=request, headers=auth_headers("ordinary"))
    assert denied.status_code == 403

    created = client.post("/api/v2/auth/users", json=request, headers=auth_headers("admin"))
    assert created.status_code == 201
    assert created.json()["role"] == "knowledge_reviewer"
    assert "password" not in created.text
    assert "digest" not in created.text

    listing = client.get("/api/v2/auth/users", headers=auth_headers("admin"))
    assert listing.status_code == 200
    usernames = {item["username"] for item in listing.json()["items"]}
    assert {"admin", "ordinary", "reviewer"} <= usernames
    reviewer = next(item for item in listing.json()["items"] if item["username"] == "reviewer")
    assert reviewer["role"] == "knowledge_reviewer"
    assert reviewer["data_scope"]["mode"] == "deny"
    assert "digest" not in listing.text
    assert client.get("/api/v2/auth/users", headers=auth_headers("ordinary")).status_code == 403


def test_request_body_cannot_choose_authenticated_identity(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    owner = seed_user("owner")
    seed_user("victim")
    response = client.post(
        "/api/v2/runs",
        json={"question": "hello", "user_id": "victim"},
        headers=auth_headers("owner"),
    )
    assert response.status_code == 201
    assert response.json()["run"]["owner_user_id"] == owner.id


def test_admin_configures_persistent_data_scope_without_exposing_it_to_user(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("scope-admin", role=Role.ADMIN)
    seed_user("scope-outsider")
    admin = auth_headers("scope-admin")
    outsider = auth_headers("scope-outsider")
    created = client.post(
        "/api/v2/auth/users",
        headers=admin,
        json={
            "username": "scoped-user",
            "password": "scoped-user-password",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    initial = client.get(f"/api/v2/auth/users/{user_id}/data-scope", headers=admin)
    assert initial.status_code == 200
    assert initial.json() == {
        "user_id": user_id,
        "mode": "deny",
        "organizations": [],
        "regions": [],
        "version": 1,
    }
    assert (
        client.get(f"/api/v2/auth/users/{user_id}/data-scope", headers=outsider).status_code == 403
    )
    assert (
        client.put(
            f"/api/v2/auth/users/{user_id}/data-scope",
            headers=outsider,
            json={"mode": "all"},
        ).status_code
        == 403
    )

    restricted = client.put(
        f"/api/v2/auth/users/{user_id}/data-scope",
        headers=admin,
        json={
            "mode": "restricted",
            "organizations": ["TOP-SECRET-ORG"],
            "regions": ["华东"],
        },
    )
    assert restricted.status_code == 200, restricted.text
    assert restricted.json()["version"] == 2
    assert restricted.json()["organizations"] == ["TOP-SECRET-ORG"]

    me = client.get(
        "/api/v2/auth/me",
        headers=auth_headers("scoped-user", password="scoped-user-password"),
    )
    assert me.status_code == 200
    assert "data_scope" not in me.json()
    assert "organizations" not in me.json()
    assert "regions" not in me.json()
    assert "TOP-SECRET-ORG" not in me.text

    audit = client.get(
        "/api/v2/admin/audit-events",
        headers=admin,
        params={"action": "identity.data_scope_updated", "resource_id": user_id},
    )
    assert audit.status_code == 200
    assert audit.json()[0]["metadata"]["mode"] == "restricted"
    assert "TOP-SECRET-ORG" not in audit.text
    assert "华东" not in audit.text

    full = client.put(
        f"/api/v2/auth/users/{user_id}/data-scope",
        headers=admin,
        json={"mode": "all"},
    )
    assert full.status_code == 200
    assert full.json()["version"] == 3


def test_invalid_scope_shapes_are_rejected_before_service_execution(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    target = seed_user("scope-target")
    seed_user("scope-shape-admin", role=Role.ADMIN)
    admin = auth_headers("scope-shape-admin")

    missing_regions = client.put(
        f"/api/v2/auth/users/{target.id}/data-scope",
        headers=admin,
        json={"mode": "restricted", "organizations": ["ORG-1"]},
    )
    values_on_all = client.put(
        f"/api/v2/auth/users/{target.id}/data-scope",
        headers=admin,
        json={"mode": "all", "organizations": ["ORG-1"]},
    )

    assert missing_regions.status_code == 422
    assert values_on_all.status_code == 422
