"""Application-database provision creates schema without leaking secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.migration_state import inspect_migration_state
from xiaoying_quick.infrastructure.persistence.provision import (
    _bootstrap_urls,
    _compile_create_table,
    _database_present,
    _is_access_denied,
    _is_missing_table,
    _is_unknown_database,
    create_missing_tables,
    ensure_database,
    is_analyticdb,
    list_application_tables,
    provision_application_database,
)
from xiaoying_quick.infrastructure.persistence.session import build_engine, configure_engine


def test_sqlite_provision_creates_tables_and_stamps_head(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'provision.sqlite'}"

    assert ensure_database(database_url) is False
    report = provision_application_database(database_url)

    engine = build_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        state = inspect_migration_state(engine)
    finally:
        engine.dispose()

    assert report.database_created is False
    assert report.schema_applied is True
    assert report.action == "created"
    assert set(Base.metadata.tables) <= set(report.tables)
    assert "identity_users" in tables
    assert "alembic_version" in tables
    assert state.is_current
    assert report.revision
    rendered = str(report.to_record())
    assert "password" not in rendered
    assert "://" not in rendered


def test_create_missing_tables_is_idempotent_without_describe(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'adb-safe.sqlite'}"
    engine = build_engine(database_url)
    try:
        first = create_missing_tables(engine)
        second = create_missing_tables(engine)
        tables = {name.lower() for name in list_application_tables(engine)}
    finally:
        engine.dispose()

    assert "run_artifacts" in {name.lower() for name in first}
    assert second == ()
    assert "run_artifacts" in tables
    assert "identity_users" in tables


def test_analyticdb_create_sql_skips_describe_and_foreign_keys() -> None:
    engine = build_engine("sqlite://")
    try:
        table = Base.metadata.tables["run_artifacts"]
        ddl = _compile_create_table(table, engine, analytic=True)
    finally:
        engine.dispose()

    assert "IF NOT EXISTS" in ddl.upper()
    assert "FOREIGN KEY" not in ddl.upper()
    assert is_analyticdb("mysql+pymysql://u:p@amv-example.ads.aliyuncs.com:3306/AgentLoop")
    assert not is_analyticdb("mysql+pymysql://u:p@rm-example.mysql.rds.aliyuncs.com:3306/AgentLoop")
    assert _is_missing_table(RuntimeError('table "AGENTLOOP.RUN_ARTIFACTS" not found'))


def test_analyticdb_engine_disables_savepoints() -> None:
    from sqlalchemy import create_engine

    engine = create_engine("mysql+pymysql://u:p@amv-example.ads.aliyuncs.com:3306/AgentLoop")
    try:
        configure_engine(engine)
        assert engine.dialect.supports_savepoints is False
    finally:
        engine.dispose()


def test_mysql_bootstrap_prefers_a_granted_database() -> None:
    url = make_url("mysql+pymysql://appuser:secret@db.example:3306/AgentLoop?charset=utf8mb4")
    names = tuple(item.database for item in _bootstrap_urls(url))
    assert names[0] == "AgentLoop"
    assert "AI_CVRM" in names
    assert "ai4bi" in names
    assert _database_present("AgentLoop", {"agentloop", "ai4bi"})
    assert _is_access_denied(RuntimeError("1044, Access denied for user 'appuser'@'%'"))
    assert _is_unknown_database(RuntimeError("(1049, \"Unknown database 'agentloop'\")"))


def test_provision_rejects_unsafe_database_names() -> None:
    with pytest.raises(ValueError, match="plain identifier"):
        provision_application_database("mysql+pymysql://app@db.example/bad-name")
