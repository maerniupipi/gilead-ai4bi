"""End-to-end API coverage for the V2 control plane."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.models.knowledge import (
    KnowledgeEntryModel,
    PersonalMemoryModel,
    PersonalMemoryRevisionModel,
)
from xiaoying_quick.infrastructure.persistence.repositories.data_sources import (
    SqlAlchemyDataSourceRepository,
)
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.infrastructure.search.knowledge_recall import (
    SqlAlchemyKnowledgeRecallSource,
)
from xiaoying_quick.infrastructure.secrets.fernet_store import LocalFernetSecretStore
from xiaoying_quick.modules.context.contracts import RecallLevel, RecallRequest
from xiaoying_quick.modules.identity.contracts import Role, UserRecord


def _sqlite_source(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table sales (brand text, value integer)")
    connection.execute("insert into sales values ('A', 1)")
    connection.commit()
    connection.close()


def _source_body(path: Path, *, password: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "sales-source",
        "connection_url": "sqlite://",
        "selected_database": str(path),
        "schema": None,
        "dialect": "sqlite",
        "ssl_mode": "disable",
        "allowed_objects": ["sales"],
        "query_timeout_seconds": 3,
        "max_rows": 100,
        "allow_private_network": False,
    }
    if password is not None:
        body["password"] = password
    return body


def test_admin_data_source_lifecycle_and_domain_binding(
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    seed_user("ordinary")
    admin = auth_headers("admin")
    source_db = tmp_path / "source.sqlite3"
    _sqlite_source(source_db)

    forbidden = client.get("/api/v2/admin/data-sources", headers=auth_headers("ordinary"))
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v2/admin/data-sources",
        json=_source_body(source_db, password="initial-control-plane-secret"),
        headers=admin,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    source_id = source["id"]
    assert source["state"] == "draft"
    assert source["ssl_mode"] == "disable"
    assert source["credential_configured"] is True
    assert "initial-control-plane-secret" not in created.text
    assert "secret_ref" not in created.text

    tested = client.post(f"/api/v2/admin/data-sources/{source_id}/test", headers=admin)
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True
    assert tested.json()["read_only"] is True
    assert "sales" in tested.json()["schema_snapshot"]["objects"]

    activated = client.post(f"/api/v2/admin/data-sources/{source_id}/activate", headers=admin)
    assert activated.status_code == 200, activated.text
    revision = activated.json()
    assert revision["revision"] == 1
    assert revision["ssl_mode"] == "disable"
    assert revision["credential_configured"] is True
    assert "secret_ref" not in activated.text

    revisions = client.get(
        f"/api/v2/admin/data-sources/{source_id}/revisions",
        headers=admin,
    )
    assert revisions.status_code == 200
    assert [item["id"] for item in revisions.json()] == [revision["id"]]
    assert "secret_ref" not in revisions.text

    missing_policy = client.post(
        "/api/v2/admin/domain-bindings",
        json={
            "domain_id": "actual",
            "lab_id": "actual",
            "revision_id": revision["id"],
        },
        headers=admin,
    )
    expanded_policy = client.post(
        "/api/v2/admin/domain-bindings",
        json={
            "domain_id": "actual",
            "lab_id": "actual",
            "revision_id": revision["id"],
            "allowed_objects": ["sales", "not_in_revision"],
        },
        headers=admin,
    )
    expanded_join_policy = client.post(
        "/api/v2/admin/domain-bindings",
        json={
            "domain_id": "actual",
            "lab_id": "actual",
            "revision_id": revision["id"],
            "allowed_objects": ["sales"],
            "allowed_join_keys": ["sales.id=not_in_domain.id"],
        },
        headers=admin,
    )
    assert missing_policy.status_code == 422
    assert expanded_policy.status_code == 422
    assert expanded_join_policy.status_code == 422

    bound = client.post(
        "/api/v2/admin/domain-bindings",
        json={
            "domain_id": "actual",
            "lab_id": "actual",
            "revision_id": revision["id"],
            "allowed_objects": ["sales"],
        },
        headers=admin,
    )
    assert bound.status_code == 201, bound.text
    assert bound.json()["data_source_revision_id"] == revision["id"]
    assert bound.json()["allowed_objects"] == ["sales"]
    assert bound.json()["allowed_schemas"] == []
    assert bound.json()["allowed_join_keys"] == []

    rotated = client.post(
        f"/api/v2/admin/data-sources/{source_id}/rotate",
        json={"password": "rotated-control-plane-secret"},
        headers=admin,
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["state"] == "draft"
    assert "rotated-control-plane-secret" not in rotated.text

    bindings_after_rotation = client.get(
        "/api/v2/admin/domain-bindings",
        headers=admin,
    )
    assert bindings_after_rotation.status_code == 200
    assert bindings_after_rotation.json()[0]["active"] is False

    disabled = client.post(f"/api/v2/admin/data-sources/{source_id}/disable", headers=admin)
    assert disabled.status_code == 200
    assert disabled.json()["state"] == "disabled"

    bindings = client.get("/api/v2/admin/domain-bindings", headers=admin)
    assert bindings.status_code == 200
    assert bindings.json()[0]["domain_id"] == "actual"


def test_attach_lab_matches_document_and_inherits_source_policy(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    labs = app.state.settings.knowledge_root / "labs"
    labs.mkdir(parents=True)
    (labs / "actual.md").write_text(
        "# Actual 实验室\n\n> lab_id: `actual`\n\n内部开票实际销售。\n",
        encoding="utf-8",
    )
    source_db = tmp_path / "lab-source.sqlite3"
    _sqlite_source(source_db)
    created = client.post(
        "/api/v2/admin/data-sources",
        json=_source_body(source_db, password="lab-source-secret"),
        headers=admin,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    missing = client.post(
        f"/api/v2/admin/data-sources/{source_id}/labs",
        json={"name": "不存在的实验室", "token": "synthetic-lab-token-value"},
        headers=admin,
    )
    assert missing.status_code == 422
    assert "没有找到对应的实验室文档" in missing.text

    attached = client.post(
        f"/api/v2/admin/data-sources/{source_id}/labs",
        json={"name": "Actual", "token": "synthetic-lab-token-value"},
        headers=admin,
    )
    assert attached.status_code == 201, attached.text
    body = attached.json()
    assert body["lab_id"] == "actual"
    assert body["name"] == "Actual"
    assert body["token_configured"] is True
    assert "synthetic-lab-token-value" not in attached.text

    listed = client.get("/api/v2/admin/data-sources", headers=admin)
    assert listed.status_code == 200
    source = next(item for item in listed.json() if item["id"] == source_id)
    assert source["state"] == "active"
    assert source["labs"][0]["lab_id"] == "actual"

    bindings = client.get("/api/v2/admin/domain-bindings", headers=admin)
    assert bindings.status_code == 200
    active = next(item for item in bindings.json() if item["active"])
    assert active["lab_id"] == "actual"
    assert active["allowed_objects"] == ["sales"]

    removed = client.delete(f"/api/v2/admin/data-sources/{source_id}/labs/actual", headers=admin)
    assert removed.status_code == 204


def test_data_source_admin_role_can_manage_sources(
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("source-admin", role=Role.DATA_SOURCE_ADMIN)
    source_db = tmp_path / "role-source.sqlite3"
    _sqlite_source(source_db)

    created = client.post(
        "/api/v2/admin/data-sources",
        json=_source_body(source_db),
        headers=auth_headers("source-admin"),
    )

    assert created.status_code == 201, created.text
    assert (
        client.get(
            "/api/v2/admin/data-sources",
            headers=auth_headers("source-admin"),
        ).status_code
        == 200
    )


def test_tls_mode_is_explicit_and_url_query_cannot_override_it(
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("tls-admin", role=Role.DATA_SOURCE_ADMIN)
    headers = auth_headers("tls-admin")
    password = "tls-control-plane-secret"
    body = {
        "name": "remote-tls-source",
        "connection_url": "mysql+pymysql://db.example.test:3306",
        "username": "reader",
        "password": password,
        "selected_database": "analytics",
        "schema": None,
        "dialect": "mysql",
        "ssl_mode": "verify_full",
    }

    created = client.post("/api/v2/admin/data-sources", json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["ssl_mode"] == "verify_full"
    assert password not in created.text
    source_id = created.json()["id"]

    updated = client.put(
        f"/api/v2/admin/data-sources/{source_id}",
        json={**body, "password": None, "ssl_mode": "require"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["ssl_mode"] == "require"

    injected = client.post(
        "/api/v2/admin/data-sources",
        json={
            **body,
            "name": "query-injected-source",
            "connection_url": "mysql+pymysql://db.example.test:3306?sslmode=disable",
        },
        headers=headers,
    )
    assert injected.status_code == 422

    source_db = tmp_path / "invalid-sqlite-tls.sqlite3"
    sqlite_tls = client.post(
        "/api/v2/admin/data-sources",
        json={**_source_body(source_db), "name": "invalid-sqlite-tls", "ssl_mode": "require"},
        headers=headers,
    )
    assert sqlite_tls.status_code == 422


def test_credential_rotation_preserves_activated_revision_secret(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    source_db = tmp_path / "immutable-secret-source.sqlite3"
    _sqlite_source(source_db)
    original = "immutable-original-password"
    replacement = "immutable-replacement-password"

    created = client.post(
        "/api/v2/admin/data-sources",
        json=_source_body(source_db, password=original),
        headers=headers,
    )
    source_id = created.json()["id"]
    activated = client.post(
        f"/api/v2/admin/data-sources/{source_id}/activate",
        headers=headers,
    )
    revision_id = activated.json()["id"]

    rotated = client.post(
        f"/api/v2/admin/data-sources/{source_id}/rotate",
        json={"password": replacement},
        headers=headers,
    )
    assert rotated.status_code == 200, rotated.text

    with session_scope(app.state.session_factory) as session:
        repository = SqlAlchemyDataSourceRepository(session)
        source = repository.get(source_id)
        revision = repository.get_revision(revision_id)
        assert source is not None
        assert revision is not None
        assert source.secret_ref is not None
        assert revision.secret_ref is not None
        assert source.secret_ref != revision.secret_ref

    secrets = app.state.secret_store
    assert isinstance(secrets, LocalFernetSecretStore)
    assert secrets.get(revision.secret_ref) == original
    assert secrets.get(source.secret_ref) == replacement


def test_personal_memory_routes_are_unavailable(client, seed_user, auth_headers):
    seed_user("alice")
    headers = auth_headers("alice")
    for method, path in (("GET","/api/v2/memory"), ("POST","/api/v2/memory"),
                         ("PATCH","/api/v2/memory/example"), ("DELETE","/api/v2/memory/example")):
        assert client.request(method, path, headers=headers).status_code == 404


def test_candidate_review_publish_reject_and_audit_flow(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    seed_user("alice")
    seed_user("bob")
    admin = auth_headers("admin")
    alice = auth_headers("alice")
    bob = auth_headers("bob")

    proposed = client.post(
        "/api/v2/knowledge/candidates",
        json={
            "scope": "domain",
            "domain_id": "demand",
            "title": "基层盘口径",
            "content": "基层盘默认进入 Demand 域",
            "rationale": "用户明确纠正过域路由",
            "evidence_refs": ["clarification-1"],
        },
        headers=alice,
    )
    assert proposed.status_code == 201, proposed.text
    candidate_id = proposed.json()["id"]
    assert proposed.json()["state"] == "pending_review"

    assert client.get("/api/v2/knowledge/candidates", headers=bob).json() == []
    assert client.get("/api/v2/knowledge/published", headers=alice).json() == []
    assert client.get("/api/v2/admin/knowledge/reviews", headers=alice).status_code == 403

    queue = client.get("/api/v2/admin/knowledge/reviews", headers=admin)
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [candidate_id]

    approved = client.post(
        f"/api/v2/admin/knowledge/reviews/{candidate_id}/approve",
        json={"comment": "口径已核验"},
        headers=admin,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["published"]["state"] == "published"

    published = client.get(
        "/api/v2/knowledge/published?scope=domain&domain_id=demand",
        headers=bob,
    )
    assert published.status_code == 200
    assert [entry["title"] for entry in published.json()] == ["基层盘口径"]

    rejected_candidate = client.post(
        "/api/v2/knowledge/candidates",
        json={
            "scope": "business",
            "title": "待拒绝规则",
            "content": "这条规则不应发布",
            "rationale": "用于验收拒绝流程",
        },
        headers=alice,
    ).json()
    rejected = client.post(
        f"/api/v2/admin/knowledge/reviews/{rejected_candidate['id']}/reject",
        json={"comment": "证据不足"},
        headers=admin,
    )
    assert rejected.status_code == 200
    assert rejected.json()["candidate"]["state"] == "rejected"

    audits = client.get("/api/v2/admin/audit-events?limit=100", headers=admin)
    assert audits.status_code == 200
    actions = {event["action"] for event in audits.json()}
    assert "knowledge_candidate.proposed" in actions
    assert "knowledge_entry.published" in actions
    assert "knowledge_candidate.rejected" in actions


def test_knowledge_reviewer_role_can_process_review_queue(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("reviewer", role=Role.KNOWLEDGE_REVIEWER)
    seed_user("author")
    proposed = client.post(
        "/api/v2/knowledge/candidates",
        json={
            "scope": "domain",
            "domain_id": "actual",
            "title": "Actual 域别名",
            "content": "内部实际销售问题属于 Actual 域",
            "rationale": "澄清结论待审核",
        },
        headers=auth_headers("author"),
    )
    candidate_id = proposed.json()["id"]
    reviewer = auth_headers("reviewer")

    queue = client.get("/api/v2/admin/knowledge/reviews", headers=reviewer)
    approved = client.post(
        f"/api/v2/admin/knowledge/reviews/{candidate_id}/approve",
        json={"comment": "已核验"},
        headers=reviewer,
    )

    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [candidate_id]
    assert approved.status_code == 200, approved.text
    assert approved.json()["published"]["published_by"]


def test_publishing_same_logical_knowledge_supersedes_old_version_and_recall(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    author = seed_user("version-author")
    admin_headers = auth_headers("admin")
    author_headers = auth_headers("version-author")

    def publish(title: str, content: str) -> dict[str, object]:
        proposed = client.post(
            "/api/v2/knowledge/candidates",
            json={
                "scope": "domain",
                "domain_id": "ACTUAL",
                "title": title,
                "content": content,
                "rationale": "同一条域知识的修订",
            },
            headers=author_headers,
        )
        assert proposed.status_code == 201, proposed.text
        reviewed = client.post(
            f"/api/v2/admin/knowledge/reviews/{proposed.json()['id']}/approve",
            json={"comment": "已核验"},
            headers=admin_headers,
        )
        assert reviewed.status_code == 200, reviewed.text
        return dict(reviewed.json()["published"])

    first = publish("ＡＣＴＵＡＬ   路由", "Actual 域路由口径 v1")
    second = publish("actual 路由", "Actual 域路由口径 v2")

    assert first["version"] == 1
    assert second["version"] == 2
    published = client.get(
        "/api/v2/knowledge/published?scope=domain&domain_id=ACTUAL",
        headers=author_headers,
    )
    assert published.status_code == 200
    assert [(item["id"], item["version"]) for item in published.json()] == [(second["id"], 2)]

    with session_scope(app.state.session_factory) as session:
        rows = session.scalars(
            select(KnowledgeEntryModel)
            .where(KnowledgeEntryModel.domain_id == "ACTUAL")
            .order_by(KnowledgeEntryModel.version)
        ).all()
        assert [(row.version, row.state, row.content) for row in rows] == [
            (1, "superseded", "Actual 域路由口径 v1"),
            (2, "published", "Actual 域路由口径 v2"),
        ]
        hits = SqlAlchemyKnowledgeRecallSource(session).search(
            RecallRequest(
                request_id="version-recall",
                level=RecallLevel.L1_UNDERSTANDING,
                actor_id=author.id,
                session_id="version-session",
                query="actual 路由",
            ),
            candidate_limit=100,
        )
        version_ids = {str(first["id"]), str(second["id"])}
        version_hits = [hit for hit in hits if hit.content_id in version_ids]
        assert [(hit.content_id, hit.version) for hit in version_hits] == [(second["id"], "2")]

    assert [entry.id for entry in app.state.knowledge_index.entries] == [second["id"]]


def test_secret_content_is_rejected_and_never_echoed(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    secret = "do-not-echo-this-secret-value"

    memory = client.post(
        "/api/v2/memory",
        json={"category": "preference", "content": f"password={secret}"},
        headers=headers,
    )
    assert memory.status_code == 404
    assert secret not in memory.text

    candidate = client.post(
        "/api/v2/knowledge/candidates",
        json={
            "scope": "business",
            "title": f"api_key={secret}",
            "content": "正常正文",
            "rationale": "正常依据",
        },
        headers=headers,
    )
    assert candidate.status_code == 422
    assert secret not in candidate.text


def test_encrypted_store_and_every_control_plane_response_hide_passwords(
    app: FastAPI,
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    del app
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    source_db = tmp_path / "secure-source.sqlite3"
    _sqlite_source(source_db)
    original = "plain-password-must-never-escape"
    rotated = "rotated-password-must-never-escape"

    created = client.post(
        "/api/v2/admin/data-sources",
        json=_source_body(source_db, password=original),
        headers=admin,
    )
    source_id = created.json()["id"]
    responses = [created]
    responses.append(client.get("/api/v2/admin/data-sources", headers=admin))
    responses.append(
        client.post(
            f"/api/v2/admin/data-sources/{source_id}/rotate",
            json={"password": rotated},
            headers=admin,
        )
    )
    responses.append(client.get("/api/v2/admin/audit-events?limit=100", headers=admin))

    for response in responses:
        assert response.status_code < 400, response.text
        assert original not in response.text
        assert rotated not in response.text
        assert "secret_ref" not in response.text

    encrypted = settings.secret_store_path.read_text(encoding="utf-8")
    assert original not in encrypted
    assert rotated not in encrypted
