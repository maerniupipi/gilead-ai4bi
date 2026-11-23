"""Packaged frontend is served by the API process when www/index.html exists."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
)


def test_api_still_works_when_frontend_is_absent(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    application = create_app(
        settings=Settings(
            environment="test",
            database_url="sqlite://",
            db_auto_create=True,
            auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
            sql_approval_hmac_secret=SecretStr("test-sql-secret-with-at-least-32-bytes"),
            secret_store_path=tmp_path / "secrets.json",
            secret_key_path=tmp_path / "master.key",
            knowledge_root=tmp_path / "knowledge",
            static_root=tmp_path / "missing-www",
        ),
        engine=engine,
        session_factory=build_session_factory(engine),
    )
    with TestClient(application) as client:
        live = client.get("/api/v2/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"


def test_packaged_frontend_is_served_from_the_same_origin(tmp_path: Path) -> None:
    www = tmp_path / "www"
    assets = www / "assets"
    assets.mkdir(parents=True)
    (www / "index.html").write_text("<html><body>quick-ui</body></html>", encoding="utf-8")
    (assets / "app.css").write_text("body{color:black}", encoding="utf-8")
    private = tmp_path / "private.txt"
    private.write_text("private-only-fixture", encoding="utf-8")
    (www / "outside.txt").symlink_to(private)
    engine = build_engine("sqlite://")
    application = create_app(
        settings=Settings(
            environment="test",
            database_url="sqlite://",
            db_auto_create=True,
            auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
            sql_approval_hmac_secret=SecretStr("test-sql-secret-with-at-least-32-bytes"),
            secret_store_path=tmp_path / "secrets.json",
            secret_key_path=tmp_path / "master.key",
            knowledge_root=tmp_path / "knowledge",
            static_root=www,
        ),
        engine=engine,
        session_factory=build_session_factory(engine),
    )
    with TestClient(application) as client:
        page = client.get("/")
        asset = client.get("/assets/app.css")
        live = client.get("/api/v2/health/live")
        for path in ("/%2e%2e%2Fprivate.txt", "/outside.txt"):
            escaped = client.get(path)
            assert "private-only-fixture" not in escaped.text

    assert page.status_code == 200
    assert "quick-ui" in page.text
    assert asset.status_code == 200
    assert "color:black" in asset.text
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
