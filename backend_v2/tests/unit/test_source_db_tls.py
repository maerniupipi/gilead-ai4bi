from __future__ import annotations

import ssl
from datetime import datetime, timezone

import pytest

from xiaoying_quick.infrastructure.source_db.sqlalchemy_adapter import (
    SqlAlchemyConnectionProbe,
    build_runtime_url,
)
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceRevision,
    DataSourceSslMode,
)


def revision(
    *,
    dialect: DataSourceDialect,
    ssl_mode: DataSourceSslMode,
    connection_url: str | None = None,
) -> DataSourceRevision:
    urls = {
        DataSourceDialect.MYSQL: "mysql+pymysql://db.example.test:3306",
        DataSourceDialect.POSTGRESQL: "postgresql+psycopg://db.example.test:5432",
        DataSourceDialect.SQLITE: "sqlite://",
    }
    return DataSourceRevision(
        id="revision-1",
        data_source_id="source-1",
        revision=1,
        connection_url=connection_url or urls[dialect],
        username=None if dialect is DataSourceDialect.SQLITE else "reader",
        selected_database=":memory:" if dialect is DataSourceDialect.SQLITE else "analytics",
        schema=None,
        dialect=dialect,
        ssl_mode=ssl_mode,
        secret_ref=None,
        allowed_objects=(),
        allowed_schemas=(),
        query_timeout_seconds=7,
        max_rows=100,
        allow_private_network=False,
        schema_snapshot_id=None,
        created_by="admin",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    ("ssl_mode", "driver_value"),
    [
        (DataSourceSslMode.DISABLE, "disable"),
        (DataSourceSslMode.PREFER, "prefer"),
        (DataSourceSslMode.REQUIRE, "require"),
        (DataSourceSslMode.VERIFY_CA, "verify-ca"),
        (DataSourceSslMode.VERIFY_FULL, "verify-full"),
    ],
)
def test_postgresql_tls_mode_is_mapped_to_psycopg(
    ssl_mode: DataSourceSslMode, driver_value: str
) -> None:
    args = SqlAlchemyConnectionProbe._connect_args(
        revision(dialect=DataSourceDialect.POSTGRESQL, ssl_mode=ssl_mode)
    )

    assert args == {"connect_timeout": 7, "sslmode": driver_value}


@pytest.mark.parametrize("ssl_mode", [DataSourceSslMode.PREFER, DataSourceSslMode.REQUIRE])
def test_mysql_prefer_and_require_enable_tls_without_plaintext_fallback(
    ssl_mode: DataSourceSslMode,
) -> None:
    args = SqlAlchemyConnectionProbe._connect_args(
        revision(dialect=DataSourceDialect.MYSQL, ssl_mode=ssl_mode)
    )

    context = args.pop("ssl")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False
    assert args == {"connect_timeout": 7, "read_timeout": 7, "write_timeout": 7}


@pytest.mark.parametrize(
    ("ssl_mode", "check_hostname"),
    [
        (DataSourceSslMode.VERIFY_CA, False),
        (DataSourceSslMode.VERIFY_FULL, True),
    ],
)
def test_mysql_verified_modes_use_system_trust_store(
    ssl_mode: DataSourceSslMode, check_hostname: bool
) -> None:
    args = SqlAlchemyConnectionProbe._connect_args(
        revision(dialect=DataSourceDialect.MYSQL, ssl_mode=ssl_mode)
    )

    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is check_hostname


def test_mysql_disable_explicitly_disables_tls() -> None:
    args = SqlAlchemyConnectionProbe._connect_args(
        revision(dialect=DataSourceDialect.MYSQL, ssl_mode=DataSourceSslMode.DISABLE)
    )

    assert args == {
        "connect_timeout": 7,
        "read_timeout": 7,
        "write_timeout": 7,
        "ssl_disabled": True,
    }


def test_sqlite_rejects_any_tls_mode_other_than_disable() -> None:
    with pytest.raises(ValueError, match="SQLite only supports disable"):
        SqlAlchemyConnectionProbe._connect_args(
            revision(dialect=DataSourceDialect.SQLITE, ssl_mode=DataSourceSslMode.REQUIRE)
        )


def test_runtime_url_rejects_query_parameter_injection() -> None:
    value = revision(
        dialect=DataSourceDialect.POSTGRESQL,
        ssl_mode=DataSourceSslMode.VERIFY_FULL,
        connection_url="postgresql+psycopg://db.example.test:5432?sslmode=disable",
    )

    with pytest.raises(ValueError, match="query parameters"):
        build_runtime_url(value, "secret")
