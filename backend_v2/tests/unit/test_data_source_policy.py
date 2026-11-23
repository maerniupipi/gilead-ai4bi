from __future__ import annotations

import pytest

from xiaoying_quick.modules.data_sources.connection_policy import (
    ConnectionPolicy,
    UnsafeConnectionTarget,
)
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceDraft,
    DataSourceSslMode,
)


def draft(**overrides) -> DataSourceDraft:
    values = {
        "name": "sales",
        "connection_url": "mysql+pymysql://db.example.test:3306",
        "username": "reader",
        "password": "write-only",
        "selected_database": "sales",
        "schema": None,
        "dialect": DataSourceDialect.MYSQL,
    }
    values.update(overrides)
    return DataSourceDraft(**values)


def test_rejects_credentials_inside_url() -> None:
    with pytest.raises(UnsafeConnectionTarget, match="不得包含账号或密码"):
        ConnectionPolicy().validate(
            draft(connection_url="mysql+pymysql://reader:secret@db.example.test:3306")
        )


def test_rejects_tls_configuration_inside_url_query() -> None:
    with pytest.raises(UnsafeConnectionTarget, match="query/fragment"):
        ConnectionPolicy().validate(
            draft(connection_url="mysql+pymysql://db.example.test:3306?sslmode=disable")
        )


def test_sqlite_only_accepts_disabled_tls() -> None:
    with pytest.raises(UnsafeConnectionTarget, match="SQLite 仅支持 disable"):
        ConnectionPolicy().validate(
            draft(
                connection_url="sqlite://",
                username=None,
                password=None,
                selected_database=":memory:",
                dialect=DataSourceDialect.SQLITE,
                ssl_mode=DataSourceSslMode.REQUIRE,
            )
        )


@pytest.mark.parametrize("ssl_mode", tuple(DataSourceSslMode))
def test_remote_sources_accept_explicit_tls_modes(ssl_mode: DataSourceSslMode) -> None:
    ConnectionPolicy().validate(draft(ssl_mode=ssl_mode))


def test_rejects_private_literal_unless_explicitly_allowed() -> None:
    with pytest.raises(UnsafeConnectionTarget, match="私网"):
        ConnectionPolicy().validate(draft(connection_url="mysql+pymysql://10.0.0.8:3306"))
    ConnectionPolicy().validate(
        draft(connection_url="mysql+pymysql://10.0.0.8:3306", allow_private_network=True)
    )


def test_rejects_link_local_even_when_private_is_allowed() -> None:
    with pytest.raises(UnsafeConnectionTarget, match="链路本地"):
        ConnectionPolicy().validate(
            draft(connection_url="mysql+pymysql://169.254.169.254:3306", allow_private_network=True)
        )
