"""Migration baseline, drift, and production startup guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence import models as models  # noqa: F401
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.migration_state import (
    SchemaNotCurrentError,
    assert_database_at_head,
    inspect_migration_state,
)
from xiaoying_quick.infrastructure.persistence.models.chat import SessionDomainPatchModel
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_initial_migration_matches_all_orm_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migrated.sqlite"
    monkeypatch.setenv("XIAOYING_DATABASE_URL", _database_url(database_path))

    command.upgrade(_config(), "head")

    engine = build_engine(_database_url(database_path))
    try:
        state = inspect_migration_state(engine)
        actual_tables = set(inspect(engine).get_table_names())
        assert state.is_current
        assert set(Base.metadata.tables) <= actual_tables
        assert "quick_jobs" in actual_tables
        command.check(_config())

        command.downgrade(_config(), "base")
        downgraded_tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables).isdisjoint(downgraded_tables)

        command.upgrade(_config(), "head")
        assert inspect_migration_state(engine).is_current
    finally:
        engine.dispose()


def test_unversioned_database_is_rejected_by_schema_guard(tmp_path: Path) -> None:
    engine = build_engine(_database_url(tmp_path / "unversioned.sqlite"))
    try:
        with pytest.raises(SchemaNotCurrentError, match="unversioned"):
            assert_database_at_head(engine)
    finally:
        engine.dispose()


def test_migration_managed_app_starts_only_after_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    database_path = tmp_path / "startup.sqlite"
    database_url = _database_url(database_path)
    runtime_settings = settings.model_copy(
        update={"database_url": database_url, "db_auto_create": False}
    )

    missing_engine = build_engine(database_url)
    missing_app = create_app(
        settings=runtime_settings,
        engine=missing_engine,
        session_factory=build_session_factory(missing_engine),
    )
    with pytest.raises(SchemaNotCurrentError):
        with TestClient(missing_app):
            pass

    monkeypatch.setenv("XIAOYING_DATABASE_URL", database_url)
    command.upgrade(_config(), "head")
    migrated_engine = build_engine(database_url)
    migrated_app = create_app(
        settings=runtime_settings,
        engine=migrated_engine,
        session_factory=build_session_factory(migrated_engine),
    )
    with TestClient(migrated_app) as client:
        readiness = client.get("/api/v2/health/ready")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "ready"


def test_topic_migration_backfills_legacy_patch_rows_and_keeps_payload_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "legacy-topic.sqlite"
    database_url = _database_url(database_path)
    monkeypatch.setenv("XIAOYING_DATABASE_URL", database_url)
    command.upgrade(_config(), "20260806_0003")
    engine = build_engine(database_url)
    old_payload = {
        "patch_id": "legacy-patch",
        "case_id": "legacy-case",
        "run_id": "legacy-run",
        "session_id": "legacy-session",
        "frame_id": "legacy-frame",
        "selected_domains": ["actual"],
        "slot_updates": [],
        "effective_at": "2026-08-06T12:00:00+00:00",
        "supersedes_plan_ids": [],
        "version": 1,
    }
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO clarification_cases "
                    "(id, run_id, session_id, frame_id, revision, status, payload, "
                    "created_at, answered_at) VALUES "
                    "(:id, :run_id, :session_id, :frame_id, 1, 'answered', :payload, "
                    ":created_at, :answered_at)"
                ),
                {
                    "id": "legacy-case",
                    "run_id": "legacy-run",
                    "session_id": "legacy-session",
                    "frame_id": "legacy-frame",
                    "payload": json.dumps({"frame_id": "legacy-frame"}),
                    "created_at": "2026-08-06 12:00:00",
                    "answered_at": "2026-08-06 12:00:01",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO session_domain_patches "
                    "(id, session_id, clarification_id, run_id, frame_id, selected_domains, "
                    "payload, active, created_at) VALUES "
                    "(:id, :session_id, :clarification_id, :run_id, :frame_id, "
                    ":selected_domains, :payload, 1, :created_at)"
                ),
                {
                    "id": "legacy-patch",
                    "session_id": "legacy-session",
                    "clarification_id": "legacy-case",
                    "run_id": "legacy-run",
                    "frame_id": "legacy-frame",
                    "selected_domains": json.dumps(["actual"]),
                    "payload": json.dumps(old_payload),
                    "created_at": "2026-08-06 12:00:00",
                },
            )
            newer_payload = {
                **old_payload,
                "patch_id": "legacy-patch-newer",
                "effective_at": "2026-08-06T12:00:01+00:00",
            }
            connection.execute(
                text(
                    "INSERT INTO session_domain_patches "
                    "(id, session_id, clarification_id, run_id, frame_id, selected_domains, "
                    "payload, active, created_at) VALUES "
                    "(:id, :session_id, :clarification_id, :run_id, :frame_id, "
                    ":selected_domains, :payload, 1, :created_at)"
                ),
                {
                    "id": "legacy-patch-newer",
                    "session_id": "legacy-session",
                    "clarification_id": "legacy-case",
                    "run_id": "legacy-run",
                    "frame_id": "legacy-frame",
                    "selected_domains": json.dumps(["actual"]),
                    "payload": json.dumps(newer_payload),
                    "created_at": "2026-08-06 12:00:01",
                },
            )

        command.upgrade(_config(), "head")

        inspector = inspect(engine)
        patch_columns = {
            item["name"]: item for item in inspector.get_columns("session_domain_patches")
        }
        case_columns = {item["name"]: item for item in inspector.get_columns("clarification_cases")}
        indexes = {item["name"]: item for item in inspector.get_indexes("session_domain_patches")}
        assert patch_columns["topic_id"]["nullable"] is False
        assert case_columns["topic_id"]["nullable"] is False
        assert indexes["uq_session_patch_one_active_topic"]["unique"] == 1

        with build_session_factory(engine)() as database:
            rows = database.scalars(
                select(SessionDomainPatchModel).order_by(
                    SessionDomainPatchModel.created_at,
                    SessionDomainPatchModel.id,
                )
            ).all()
            assert [(row.id, row.active) for row in rows] == [
                ("legacy-patch", False),
                ("legacy-patch-newer", True),
            ]
            assert {row.topic_id for row in rows} == {"legacy-frame"}
    finally:
        engine.dispose()
