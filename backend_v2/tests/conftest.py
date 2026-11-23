"""Shared API and persistence fixtures for the V2 backend."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from xiaoying_quick.api.dependencies import build_identity_service
from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence import models as _orm_models  # noqa: F401
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.modules.identity.contracts import DataAccessScope, Role, UserRecord
from xiaoying_quick.modules.identity.security import PasswordHasher

TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True, scope="session")
def hermetic_settings() -> Iterator[None]:
    """Cut every Settings() in the suite off from the local machine.

    A developer's .env decides which adapters the container wires — including
    whether it points at a live model endpoint. Tests must answer that question
    themselves, so the env file and any XIAOYING_* variables are taken away for
    the duration of the session.
    """

    original_env_file = Settings.model_config.get("env_file")
    leaked = {key: value for key, value in os.environ.items() if key.startswith("XIAOYING_")}
    Settings.model_config["env_file"] = None
    for key in leaked:
        del os.environ[key]
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original_env_file
        os.environ.update(leaked)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        chatbot_mode="full",  # Legacy API scenarios; dual mode has separate coverage.
        # Background jobs and HTTP fixtures need independent connections, as in production.
        database_url=f"sqlite:///{tmp_path / 'control.sqlite3'}",
        db_auto_create=True,
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        auth_issuer="xiaoying-test",
        auth_token_ttl_seconds=3600,
        secret_store_path=tmp_path / "secrets.json",
        secret_key_path=tmp_path / "master.key",
        branding_assets_path=tmp_path / "branding",
        knowledge_root=tmp_path / "knowledge",
        sse_poll_seconds=0.05,
        sse_heartbeat_seconds=1.0,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    engine = build_engine(settings.database_url)
    # Unit tests never enter the lifespan, so the schema is created here.
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    application = create_app(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
    )
    application.state.password_hasher = PasswordHasher(iterations=100_000)
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seed_user(app: FastAPI) -> Callable[..., UserRecord]:
    def seed(
        username: str,
        *,
        password: str = TEST_PASSWORD,
        role: Role = Role.USER,
        display_name: str | None = None,
        data_scope: DataAccessScope | None = None,
    ) -> UserRecord:
        with session_scope(app.state.session_factory) as session:
            service = build_identity_service(
                session,
                token_service=app.state.token_service,
                password_hasher=app.state.password_hasher,
            )
            return service.create_user(
                username=username,
                password=password,
                display_name=display_name,
                role=role,
                data_scope=data_scope or DataAccessScope.full_access(),
            )

    return seed


@pytest.fixture
def token_for(client: TestClient) -> Callable[..., str]:
    def issue(username: str, *, password: str = TEST_PASSWORD) -> str:
        response = client.post(
            "/api/v2/auth/token",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return str(response.json()["access_token"])

    return issue


@pytest.fixture
def auth_headers(token_for: Callable[..., str]) -> Callable[..., dict[str, str]]:
    def headers(username: str, *, password: str = TEST_PASSWORD) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_for(username, password=password)}"}

    return headers


@pytest.fixture
def user_count(app: FastAPI) -> Callable[[], int]:
    def count() -> int:
        with app.state.session_factory() as session:
            return SqlAlchemyUserRepository(session).count()

    return count
