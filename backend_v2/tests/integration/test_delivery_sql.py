from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.workspace import WorkspaceStore

ROOT = Path(__file__).resolve().parents[3]


def test_checked_in_sql_matches_current_application_structures():
    generator = runpy.run_path(str(ROOT / "deploy/generate_sql.py"))
    for relative, contents in generator["generated_files"]().items():
        assert (ROOT / "deploy/sql" / relative).read_text() == contents, relative


def test_sqlite_sql_initializes_control_uploads_and_boards_without_private_data(tmp_path):
    for sql_name, filename in (
        ("001_control_schema.sql", "control.sqlite3"),
        ("002_chatbots_schema.sql", "chatbots.sqlite3"),
        ("003_workspaces_schema.sql", "workspaces.sqlite3"),
    ):
        with sqlite3.connect(tmp_path / filename) as database:
            database.executescript((ROOT / "deploy/sql/sqlite" / sql_name).read_text())
    engine = create_engine(f"sqlite:///{tmp_path / 'control.sqlite3'}")
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        engine.dispose()
    with sqlite3.connect(tmp_path / "control.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM identity_users").fetchone()[0] == 0
    bots = ChatbotStore(tmp_path / "chatbots.sqlite3", mode="dual")
    assert {bot["id"] for bot in bots.list()} == {"ddi", "xlsx"}
    assert bots.personal_workbooks("xlsx", "new-user") == []
    assert WorkspaceStore(tmp_path / "workspaces.sqlite3").list("new-user") == []
