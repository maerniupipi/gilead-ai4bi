from __future__ import annotations

import hashlib
import json
import ssl
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.pool import NullPool

from ...modules.data_sources.contracts import (
    ConnectionTestResult,
    DataSourceDialect,
    DataSourceRevision,
    DataSourceSslMode,
    SchemaSnapshot,
)


def build_runtime_url(revision: DataSourceRevision, password: str | None) -> URL:
    base = make_url(revision.connection_url)
    if base.username is not None or base.password is not None:
        raise ValueError("stored connection URL must not contain credentials")
    if base.query:
        raise ValueError("stored connection URL must not contain query parameters")
    if revision.dialect is DataSourceDialect.SQLITE:
        database = revision.selected_database or base.database
        return base.set(database=database)
    return base.set(
        username=revision.username,
        password=password,
        database=revision.selected_database,
    )


class SqlAlchemyConnectionProbe:
    def test(self, revision: DataSourceRevision, password: str | None) -> ConnectionTestResult:
        started = time.perf_counter()
        try:
            url = build_runtime_url(revision, password)
            engine = create_engine(
                url,
                poolclass=NullPool,
                pool_pre_ping=True,
                connect_args=self._connect_args(revision),
            )
            try:
                with engine.connect() as connection:
                    self._enforce_read_only(
                        connection, revision.dialect, revision.query_timeout_seconds
                    )
                    connection.execute(text("SELECT 1"))
                    snapshot = self._snapshot(connection, revision)
                    version = self._server_version(connection, revision.dialect)
                latency = int((time.perf_counter() - started) * 1000)
                return ConnectionTestResult(
                    ok=True,
                    latency_ms=latency,
                    database=revision.selected_database,
                    server_version=version,
                    read_only=True,
                    schema_snapshot=snapshot,
                )
            finally:
                engine.dispose()
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return ConnectionTestResult(
                ok=False,
                latency_ms=latency,
                read_only=None,
                errors=(self._safe_error(exc),),
            )

    @staticmethod
    def _connect_args(revision: DataSourceRevision) -> dict[str, Any]:
        seconds = max(1, revision.query_timeout_seconds)
        ssl_mode = DataSourceSslMode(revision.ssl_mode)
        if revision.dialect is DataSourceDialect.SQLITE:
            if ssl_mode is not DataSourceSslMode.DISABLE:
                raise ValueError("SQLite only supports disable TLS mode")
            return {"timeout": seconds}
        if revision.dialect is DataSourceDialect.MYSQL:
            return {
                "connect_timeout": seconds,
                "read_timeout": seconds,
                "write_timeout": seconds,
                **SqlAlchemyConnectionProbe._mysql_tls_args(ssl_mode),
            }
        return {
            "connect_timeout": seconds,
            "sslmode": ssl_mode.value.replace("_", "-"),
        }

    @staticmethod
    def _mysql_tls_args(ssl_mode: DataSourceSslMode) -> dict[str, Any]:
        if ssl_mode is DataSourceSslMode.DISABLE:
            return {"ssl_disabled": True}

        if ssl_mode in {DataSourceSslMode.PREFER, DataSourceSslMode.REQUIRE}:
            # PyMySQL has no prefer-with-plaintext-fallback switch. Both modes
            # therefore require an encrypted transport and skip certificate
            # verification, avoiding an implicit downgrade to plaintext.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return {"ssl": context}

        context = ssl.create_default_context()
        context.check_hostname = ssl_mode is DataSourceSslMode.VERIFY_FULL
        context.verify_mode = ssl.CERT_REQUIRED
        return {"ssl": context}

    @staticmethod
    def _enforce_read_only(
        connection: Connection,
        dialect: DataSourceDialect,
        timeout_seconds: int,
    ) -> None:
        if dialect is DataSourceDialect.SQLITE:
            connection.exec_driver_sql("PRAGMA query_only = ON")
            return
        if dialect is DataSourceDialect.POSTGRESQL:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = {int(timeout_seconds * 1000)}"
            )
            return
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_seconds * 1000)}"
            )
        except (OperationalError, ProgrammingError):
            # AnalyticDB MySQL rejects several session SET forms.
            return

    @staticmethod
    def _snapshot(connection: Connection, revision: DataSourceRevision) -> SchemaSnapshot:
        try:
            inspector = inspect(connection)
            schema = revision.schema or None
            table_names = sorted(inspector.get_table_names(schema=schema))
            view_names = sorted(inspector.get_view_names(schema=schema))
            objects = tuple(sorted(set(table_names + view_names)))
            columns: dict[str, tuple[str, ...]] = {}
            for object_name in objects:
                values = inspector.get_columns(object_name, schema=schema)
                columns[object_name] = tuple(str(value["name"]) for value in values)
        except (OperationalError, ProgrammingError):
            objects, columns = SqlAlchemyConnectionProbe._snapshot_via_show(connection, revision)
        canonical = json.dumps(
            {"objects": objects, "columns": columns}, sort_keys=True, ensure_ascii=False
        )
        return SchemaSnapshot(
            id=f"schema_{uuid4().hex}",
            data_source_id=revision.data_source_id,
            fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            objects=objects,
            columns=columns,
            captured_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _snapshot_via_show(
        connection: Connection, revision: DataSourceRevision
    ) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
        schema = revision.selected_database or revision.schema
        if schema:
            rows = connection.exec_driver_sql(f"SHOW TABLES FROM `{schema}`").fetchall()
        else:
            rows = connection.exec_driver_sql("SHOW TABLES").fetchall()
        objects = tuple(sorted({str(row[0]) for row in rows}))
        columns: dict[str, tuple[str, ...]] = {}
        for object_name in objects:
            quoted = object_name.replace("`", "")
            field_rows = connection.exec_driver_sql(f"SHOW COLUMNS FROM `{quoted}`").fetchall()
            columns[object_name] = tuple(str(row[0]) for row in field_rows)
        return objects, columns

    @staticmethod
    def _server_version(connection: Connection, dialect: DataSourceDialect) -> str | None:
        try:
            if dialect is DataSourceDialect.SQLITE:
                return str(connection.exec_driver_sql("SELECT sqlite_version()").scalar_one())
            return str(connection.exec_driver_sql("SELECT version()").scalar_one())
        except Exception:
            return None

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        # Driver errors may echo URLs or passwords. Do not expose their text.
        return f"{type(exc).__name__}: connection check failed"


class SqlAlchemyReadOnlyRunner:
    """Low-level adapter. It receives an already-authorized SQL string only."""

    def execute(
        self,
        *,
        revision: DataSourceRevision,
        password: str | None,
        sql: str,
        max_rows: int,
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool, int]:
        url = build_runtime_url(revision, password)
        engine = create_engine(
            url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args=SqlAlchemyConnectionProbe._connect_args(revision),
        )
        started = time.perf_counter()
        try:
            with engine.connect() as connection:
                SqlAlchemyConnectionProbe._enforce_read_only(
                    connection, revision.dialect, revision.query_timeout_seconds
                )
                result = connection.execute(text(sql))
                columns = tuple(result.keys())
                fetched = result.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows = tuple(
                    tuple(_json_cell(value) for value in row) for row in fetched[:max_rows]
                )
            return columns, rows, truncated, int((time.perf_counter() - started) * 1000)
        finally:
            engine.dispose()


def _json_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        as_int = value.to_integral_value()
        if value == as_int:
            return int(as_int)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
