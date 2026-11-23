from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from xiaoying_quick.shared.compat import StrEnum


class DataSourceState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class DataSourceDialect(StrEnum):
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"


class DataSourceSslMode(StrEnum):
    DISABLE = "disable"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify_ca"
    VERIFY_FULL = "verify_full"


@dataclass(frozen=True)
class DataSourceDraft:
    name: str
    connection_url: str
    username: str | None
    password: str | None
    selected_database: str
    schema: str | None
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode = DataSourceSslMode.DISABLE
    allowed_objects: tuple[str, ...] = ()
    allowed_schemas: tuple[str, ...] = ()
    query_timeout_seconds: int = 15
    max_rows: int = 2_000
    allow_private_network: bool = False


@dataclass(frozen=True)
class DataSourceRecord:
    id: str
    name: str
    connection_url: str
    username: str | None
    selected_database: str
    schema: str | None
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode
    state: DataSourceState
    current_revision: int
    secret_ref: str | None
    allowed_objects: tuple[str, ...]
    allowed_schemas: tuple[str, ...]
    query_timeout_seconds: int
    max_rows: int
    allow_private_network: bool
    created_at: datetime
    updated_at: datetime

    def as_view(self) -> DataSourceView:
        return DataSourceView(
            id=self.id,
            name=self.name,
            connection_url=self.connection_url,
            username=self.username,
            selected_database=self.selected_database,
            schema=self.schema,
            dialect=self.dialect,
            ssl_mode=self.ssl_mode,
            state=self.state,
            current_revision=self.current_revision,
            credential_configured=bool(self.secret_ref),
            allowed_objects=self.allowed_objects,
            allowed_schemas=self.allowed_schemas,
            query_timeout_seconds=self.query_timeout_seconds,
            max_rows=self.max_rows,
            allow_private_network=self.allow_private_network,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True)
class DataSourceView:
    """Safe control-plane projection. It intentionally has no password/secret_ref."""

    id: str
    name: str
    connection_url: str
    username: str | None
    selected_database: str
    schema: str | None
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode
    state: DataSourceState
    current_revision: int
    credential_configured: bool
    allowed_objects: tuple[str, ...]
    allowed_schemas: tuple[str, ...]
    query_timeout_seconds: int
    max_rows: int
    allow_private_network: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DataSourceRevision:
    id: str
    data_source_id: str
    revision: int
    connection_url: str
    username: str | None
    selected_database: str
    schema: str | None
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode
    secret_ref: str | None
    allowed_objects: tuple[str, ...]
    allowed_schemas: tuple[str, ...]
    query_timeout_seconds: int
    max_rows: int
    allow_private_network: bool
    schema_snapshot_id: str | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class SourceLab:
    id: str
    data_source_id: str
    lab_id: str
    name: str
    token_secret_ref: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class DomainBinding:
    id: str
    domain_id: str
    lab_id: str
    data_source_id: str
    data_source_revision_id: str
    allowed_objects: tuple[str, ...]
    allowed_schemas: tuple[str, ...]
    allowed_join_keys: tuple[str, ...]
    active: bool
    created_by: str
    created_at: datetime

    @property
    def policy_fingerprint(self) -> str:
        payload = {
            "allowed_join_keys": self.allowed_join_keys,
            "allowed_objects": self.allowed_objects,
            "allowed_schemas": self.allowed_schemas,
            "domain_id": self.domain_id,
            "revision_id": self.data_source_revision_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SchemaSnapshot:
    id: str
    data_source_id: str
    fingerprint: str
    objects: tuple[str, ...]
    columns: dict[str, tuple[str, ...]]
    captured_at: datetime


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    latency_ms: int
    database: str | None = None
    server_version: str | None = None
    read_only: bool | None = None
    schema_snapshot: SchemaSnapshot | None = None
    errors: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
