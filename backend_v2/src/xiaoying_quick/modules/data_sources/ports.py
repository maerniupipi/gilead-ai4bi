from __future__ import annotations

import builtins
from typing import Protocol

from .contracts import (
    ConnectionTestResult,
    DataSourceDraft,
    DataSourceRecord,
    DataSourceRevision,
    DomainBinding,
    SchemaSnapshot,
    SourceLab,
)


class DataSourceRepository(Protocol):
    def list(self) -> builtins.list[DataSourceRecord]: ...

    def get(self, data_source_id: str) -> DataSourceRecord | None: ...

    def create(
        self, data_source_id: str, draft: DataSourceDraft, secret_ref: str | None
    ) -> DataSourceRecord: ...

    def update(
        self, data_source_id: str, draft: DataSourceDraft, secret_ref: str | None
    ) -> DataSourceRecord: ...

    def set_state(self, data_source_id: str, state: str) -> DataSourceRecord: ...

    def save_schema_snapshot(self, snapshot: SchemaSnapshot) -> SchemaSnapshot: ...

    def get_schema_snapshot(self, snapshot_id: str) -> SchemaSnapshot | None: ...

    def create_revision(
        self,
        record: DataSourceRecord,
        actor_id: str,
        schema_snapshot_id: str | None,
    ) -> DataSourceRevision: ...

    def get_revision(self, revision_id: str) -> DataSourceRevision | None: ...

    def list_revisions(self, data_source_id: str) -> builtins.list[DataSourceRevision]: ...

    def bind_domain(
        self,
        binding_id: str,
        domain_id: str,
        lab_id: str,
        revision: DataSourceRevision,
        actor_id: str,
        allowed_objects: tuple[str, ...],
        allowed_schemas: tuple[str, ...],
        allowed_join_keys: tuple[str, ...],
    ) -> DomainBinding: ...

    def list_bindings(self) -> builtins.list[DomainBinding]: ...

    def get_active_binding(self, domain_id: str) -> DomainBinding | None: ...

    def current_domain_policy_fingerprint(
        self,
        domain_id: str,
        data_source_revision_id: str,
    ) -> str | None: ...

    def deactivate_bindings_for_source(self, data_source_id: str) -> int: ...

    def list_labs(self) -> builtins.list[SourceLab]: ...

    def list_labs_for_source(self, data_source_id: str) -> builtins.list[SourceLab]: ...

    def get_lab(self, lab_row_id: str) -> SourceLab | None: ...

    def get_lab_by_lab_id(self, lab_id: str) -> SourceLab | None: ...

    def upsert_lab(self, lab: SourceLab) -> SourceLab: ...

    def delete_lab(self, lab_row_id: str) -> None: ...


class SecretStore(Protocol):
    def put(self, value: str, *, current_ref: str | None = None) -> str: ...

    def get(self, secret_ref: str) -> str: ...

    def delete(self, secret_ref: str) -> None: ...


class ConnectionProbe(Protocol):
    def test(self, revision: DataSourceRevision, password: str | None) -> ConnectionTestResult: ...


class DataSourceAuditSink(Protocol):
    def record(
        self,
        *,
        actor_id: str,
        action: str,
        resource_id: str,
        metadata: dict[str, object],
    ) -> None: ...
