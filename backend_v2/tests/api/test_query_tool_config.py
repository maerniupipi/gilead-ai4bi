from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from xiaoying_quick.modules.identity.contracts import Role, UserRecord


def _sqlite_source(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table sales (brand text, channel text)")
    connection.execute("create table other (id integer)")
    connection.commit()
    connection.close()


def test_query_tool_config_probe_and_save(
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")
    db = tmp_path / "source.sqlite3"
    _sqlite_source(db)

    empty = client.get("/api/v2/admin/tools/query_db/config", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["source"] is None

    body = {
        "name": "智能体查询库",
        "connection_url": "sqlite://",
        "selected_database": str(db),
        "dialect": "sqlite",
        "ssl_mode": "disable",
        "allow_private_network": True,
    }
    probed = client.post("/api/v2/admin/tools/query_db/probe", json=body, headers=headers)
    assert probed.status_code == 200, probed.text
    assert probed.json()["ok"] is True
    assert "sales" in probed.json()["tables"]
    assert "other" in probed.json()["tables"]

    saved = client.put(
        "/api/v2/admin/tools/query_db/config",
        json={**body, "allowed_objects": ["sales"]},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["selected"] == ["sales"]
    assert saved.json()["source"]["state"] == "active"

    loaded = client.get("/api/v2/admin/tools/query_db/config", headers=headers)
    assert loaded.json()["form"]["selected_database"] == str(db)
    assert "sales" in loaded.json()["selected"]

    tools = client.get("/api/v2/admin/tools", headers=headers)
    query = next(item for item in tools.json()["items"] if item["name"] == "query_db")
    assert query["label"] == "数据库查询"
    assert query["configurable"] is True
    assert "inspect_schema" in {item["name"] for item in tools.json()["items"]}


def test_query_tool_config_requires_tables(
    client: TestClient,
    tmp_path: Path,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    db = tmp_path / "source.sqlite3"
    _sqlite_source(db)
    response = client.put(
        "/api/v2/admin/tools/query_db/config",
        json={
            "connection_url": "sqlite://",
            "selected_database": str(db),
            "dialect": "sqlite",
            "allowed_objects": [],
        },
        headers=auth_headers("admin"),
    )
    assert response.status_code == 422
