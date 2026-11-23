import importlib.util
from pathlib import Path

from xiaoying_quick.infrastructure.persistence.session import build_engine
from xiaoying_quick.infrastructure.persistence.sql_script import (
    apply_sql_script,
    should_skip_statement,
    split_sql_statements,
)


def _sanitize_create():
    path = Path(__file__).resolve().parents[2] / "tools" / "dump_sae_sql.py"
    spec = importlib.util.spec_from_file_location("dump_sae_sql", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sanitize_create


def test_sanitize_create_keeps_set_null_from_becoming_index_null() -> None:
    ddl = (
        "CREATE TABLE `chat_messages` (\n"
        "  `id` varchar(64) NOT NULL,\n"
        "  `content` mediumtext NOT NULL,\n"
        "  PRIMARY KEY (`id`),\n"
        "  KEY `ix_chat_messages_session_created` (`session_id`,`created_at`),\n"
        "  CONSTRAINT `c1` FOREIGN KEY (`session_id`) "
        "REFERENCES `chat_sessions` (`id`) ON DELETE CASCADE,\n"
        "  CONSTRAINT `c2` FOREIGN KEY (`run_id`) "
        "REFERENCES `runs` (`id`) ON DELETE SET NULL\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
    )
    cleaned = _sanitize_create()(ddl)
    assert "FOREIGN KEY" not in cleaned.upper()
    assert "MEDIUMTEXT" not in cleaned.upper()
    assert "TEXT" in cleaned.upper()
    assert ") NULL" not in cleaned
    assert "ENGINE=" not in cleaned.upper()


def test_split_sql_keeps_semicolons_inside_strings() -> None:
    script = """
    SET NAMES utf8mb4;
    -- comment
    INSERT INTO t (c) VALUES ('a;b'), ('c');
    USE `AgentLoop`;
    """
    statements = split_sql_statements(script)
    assert statements[0].startswith("SET NAMES")
    assert "a;b" in statements[1]
    assert statements[2].upper().startswith("USE ")


def test_skip_session_and_database_statements() -> None:
    assert should_skip_statement("SET FOREIGN_KEY_CHECKS=0")
    assert should_skip_statement("CREATE DATABASE IF NOT EXISTS `AgentLoop`")
    assert should_skip_statement("USE `AgentLoop`")
    assert not should_skip_statement("CREATE TABLE IF NOT EXISTS t (id INT)")


def test_apply_sql_script_runs_on_sqlite(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'import.sqlite'}")
    try:
        report = apply_sql_script(
            engine,
            """
            SET NAMES utf8mb4;
            CREATE TABLE IF NOT EXISTS import_probe (id VARCHAR(8) PRIMARY KEY);
            INSERT INTO import_probe (id) VALUES ('ok');
            """,
        )
        assert report["executed"] == 2
        assert report["skipped"] == 1
        with engine.connect() as connection:
            row = connection.exec_driver_sql("SELECT id FROM import_probe").first()
        assert row[0] == "ok"
    finally:
        engine.dispose()
