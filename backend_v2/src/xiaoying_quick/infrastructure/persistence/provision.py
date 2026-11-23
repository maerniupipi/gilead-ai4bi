"""Create the application database and bring its schema to the current head."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, MetaData, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.schema import CreateIndex, CreateTable

from xiaoying_quick.infrastructure.persistence import models as models  # noqa: F401
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.migration_state import (
    MigrationState,
    expected_migration_heads,
    inspect_migration_state,
    migration_script_location,
)
from xiaoying_quick.infrastructure.persistence.session import configure_engine

_SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MYSQL_DIALECTS = frozenset({"mysql", "mariadb"})
_BOOTSTRAP_DATABASES = ("AI_CVRM", "ai4bi", "mysql", "information_schema")


@dataclass(frozen=True)
class ProvisionReport:
    dialect: str
    host: str | None
    database: str
    database_created: bool
    schema_applied: bool
    action: str
    tables: tuple[str, ...]
    revision: str | None

    def to_record(self) -> dict[str, object]:
        return {
            "dialect": self.dialect,
            "host": self.host,
            "database": self.database,
            "database_created": self.database_created,
            "schema_applied": self.schema_applied,
            "action": self.action,
            "tables": list(self.tables),
            "revision": self.revision,
        }


def provision_application_database(database_url: str) -> ProvisionReport:
    """Create the configured database if needed, then apply the application schema."""

    url = make_url(database_url)
    database_name = url.database
    if not database_name:
        raise ValueError("DATABASE_URL must include a database name")
    if url.get_backend_name() in _MYSQL_DIALECTS:
        _assert_safe_database_name(database_name)

    created = ensure_database(url)
    engine = configure_engine(create_engine(url, pool_pre_ping=True))
    try:
        action, revision = apply_schema(engine, database_url)
        tables = tuple(sorted(list_application_tables(engine)))
    finally:
        engine.dispose()

    return ProvisionReport(
        dialect=url.get_backend_name(),
        host=url.host,
        database=database_name,
        database_created=created,
        schema_applied=True,
        action=action,
        tables=tables,
        revision=revision,
    )


def inspect_application_database(database_url: str) -> ProvisionReport:
    url = make_url(database_url)
    database_name = url.database or ""
    engine = configure_engine(create_engine(url, pool_pre_ping=True))
    try:
        tables = tuple(sorted(list_application_tables(engine)))
        state = _safe_migration_state(engine)
        revision = ",".join(state.current_heads) if state.current_heads else None
        action = "current" if state.is_current else "pending"
    except (OperationalError, ProgrammingError):
        tables = ()
        revision = None
        action = "missing"
    finally:
        engine.dispose()

    return ProvisionReport(
        dialect=url.get_backend_name(),
        host=url.host,
        database=database_name,
        database_created=False,
        schema_applied=action == "current",
        action=action,
        tables=tables,
        revision=revision,
    )


def ensure_database(url: URL | str) -> bool:
    """Create the MySQL/MariaDB schema if this account is allowed to.

    RDS users may be unable to connect with ``database=None``. Bootstrap
    through a permitted database only to issue ``CREATE DATABASE``; tables are
    always created in the configured application schema.
    """

    parsed = make_url(url) if isinstance(url, str) else url
    if parsed.get_backend_name() not in _MYSQL_DIALECTS:
        return False
    database_name = parsed.database
    if not database_name:
        raise ValueError("DATABASE_URL must include a database name")
    _assert_safe_database_name(database_name)

    last_error: OperationalError | None = None
    for bootstrap in _bootstrap_urls(parsed):
        engine = configure_engine(
            create_engine(bootstrap, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        )
        try:
            with engine.connect() as connection:
                existing = {
                    str(row[0]) for row in connection.execute(text("SHOW DATABASES")).fetchall()
                }
                if _database_present(database_name, existing):
                    return False
                try:
                    connection.execute(
                        text(
                            f"CREATE DATABASE `{database_name}` "
                            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                except OperationalError as exc:
                    if _is_access_denied(exc):
                        return False
                    raise
                return True
        except OperationalError as exc:
            last_error = exc
            if not (_is_access_denied(exc) or _is_unknown_database(exc)):
                raise
        finally:
            engine.dispose()
    if last_error is not None:
        raise last_error
    return False


def _bootstrap_urls(parsed: URL) -> tuple[URL, ...]:
    names: list[str] = []
    if parsed.database:
        names.append(parsed.database)
    for candidate in _BOOTSTRAP_DATABASES:
        if candidate not in names:
            names.append(candidate)
    return tuple(parsed.set(database=name) for name in names)


def _database_present(name: str, existing: set[str]) -> bool:
    lowered = {item.lower() for item in existing}
    return name in existing or name.lower() in lowered


def _is_access_denied(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "access denied" in message or "(1044," in message or "(1045," in message


def _is_unknown_database(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "unknown database" in message or "(1049," in message


def apply_schema(engine: Engine, database_url: str) -> tuple[str, str | None]:
    """Create missing tables and make sure Alembic is stamped at head.

    AnalyticDB MySQL rejects ``DESCRIBE`` on a missing table (error 1064),
    which breaks SQLAlchemy ``create_all(checkfirst=True)``. Table presence is
    therefore taken from ``SHOW TABLES`` / ``sqlite_master``.
    """

    existing = list_application_tables(engine)
    state = _safe_migration_state(engine)
    expected = {name.lower() for name in Base.metadata.tables}
    if state.is_current and expected <= {name.lower() for name in existing}:
        return "already_current", _revision(state.current_heads)

    create_missing_tables(engine)
    if not state.current_heads:
        _stamp_head_safe(engine, database_url)
        return ("stamped_head" if existing else "created"), _head_revision()

    try:
        _upgrade_head(database_url)
    except (OperationalError, ProgrammingError):
        _stamp_head_safe(engine, database_url)
    return "upgraded", _head_revision()


def list_application_tables(engine: Engine) -> set[str]:
    if engine.dialect.name == "postgresql":
        from sqlalchemy import inspect

        return set(inspect(engine).get_table_names())
    schema = engine.url.database
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        elif schema:
            rows = connection.execute(text(f"SHOW TABLES FROM `{schema}`"))
        else:
            rows = connection.execute(text("SHOW TABLES"))
        return {str(row[0]) for row in rows}


def create_missing_tables(engine: Engine) -> tuple[str, ...]:
    existing = {name.lower() for name in list_application_tables(engine)}
    created: list[str] = []
    analytic = is_analyticdb(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name.lower() not in existing:
                connection.execute(text(_compile_create_table(table, engine, analytic=analytic)))
                created.append(table.name)
            if analytic:
                continue
            for index in table.indexes:
                try:
                    connection.execute(CreateIndex(index, if_not_exists=True))
                except (OperationalError, ProgrammingError):
                    try:
                        connection.execute(CreateIndex(index))
                    except (OperationalError, ProgrammingError):
                        continue
    return tuple(created)


def is_analyticdb(target: Engine | URL | str) -> bool:
    if isinstance(target, Engine):
        host = target.url.host or ""
    else:
        host = make_url(target).host or ""
    lowered = host.lower()
    return "ads.aliyuncs.com" in lowered or "analyticdb" in lowered


def _compile_create_table(table: object, engine: Engine, *, analytic: bool) -> str:
    source = _strip_adb_constraints(table) if analytic else table
    statement = CreateTable(
        source,
        include_foreign_key_constraints=[] if analytic else None,
    )
    ddl = str(statement.compile(dialect=engine.dialect))
    if "IF NOT EXISTS" not in ddl.upper():
        ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
    return ddl


def _strip_adb_constraints(table: object) -> object:
    copied = table.to_metadata(MetaData())  # type: ignore[attr-defined]
    for constraint in list(copied.constraints):
        if isinstance(constraint, (ForeignKeyConstraint, CheckConstraint)):
            copied.constraints.discard(constraint)
    return copied


def _safe_migration_state(engine: Engine) -> MigrationState:
    try:
        return inspect_migration_state(engine)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table(exc):
            return MigrationState(current_heads=(), expected_heads=expected_migration_heads())
        raise


def _is_missing_table(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "not found" in message
        or "doesn't exist" in message
        or "does not exist" in message
        or "unknown table" in message
        or "(1146," in message
    )


def _stamp_head_safe(engine: Engine, database_url: str) -> None:
    try:
        _stamp_head(database_url)
        return
    except (OperationalError, ProgrammingError):
        pass
    head = _head_revision()
    if head is None:
        return
    version = head.split(",")[0]
    with engine.begin() as connection:
        existing = {name.lower() for name in list_application_tables(engine)}
        if "alembic_version" not in existing:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                    "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
            {"version": version},
        )


def _stamp_head(database_url: str) -> None:
    _run_alembic(database_url, lambda config: command.stamp(config, "head"))


def _upgrade_head(database_url: str) -> None:
    _run_alembic(database_url, lambda config: command.upgrade(config, "head"))


def _run_alembic(database_url: str, operation: Callable[[Config], None]) -> None:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    previous = os.environ.get("XIAOYING_DATABASE_URL")
    os.environ["XIAOYING_DATABASE_URL"] = database_url
    try:
        operation(config)
    finally:
        if previous is None:
            os.environ.pop("XIAOYING_DATABASE_URL", None)
        else:
            os.environ["XIAOYING_DATABASE_URL"] = previous


def _head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory(str(migration_script_location()))
    return _revision(tuple(sorted(scripts.get_heads())))


def _revision(heads: tuple[str, ...]) -> str | None:
    return ",".join(heads) if heads else None


def _assert_safe_database_name(name: str) -> None:
    if not _SAFE_DATABASE_NAME.fullmatch(name):
        raise ValueError("database name must be a plain identifier")


def main() -> None:
    from xiaoying_quick.bootstrap.settings import Settings

    report = provision_application_database(Settings().database_url)
    print(report.to_record())


if __name__ == "__main__":
    main()
