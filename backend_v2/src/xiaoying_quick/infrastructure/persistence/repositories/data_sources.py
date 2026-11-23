from __future__ import annotations

import builtins
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceDraft,
    DataSourceRecord,
    DataSourceRevision,
    DataSourceSslMode,
    DataSourceState,
    DomainBinding,
    SchemaSnapshot,
    SourceLab,
)
from ....shared.ids import new_id
from ..models.data_sources import (
    AuditEventModel,
    DataSourceModel,
    DataSourceRevisionModel,
    DomainBindingModel,
    SchemaSnapshotModel,
    SourceLabModel,
)


class SqlAlchemyDataSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> builtins.list[DataSourceRecord]:
        rows = self._session.scalars(select(DataSourceModel).order_by(DataSourceModel.name)).all()
        return [self._record(row) for row in rows]

    def get(self, data_source_id: str) -> DataSourceRecord | None:
        row = self._session.get(DataSourceModel, data_source_id)
        return self._record(row) if row else None

    def create(
        self, data_source_id: str, draft: DataSourceDraft, secret_ref: str | None
    ) -> DataSourceRecord:
        now = datetime.now(timezone.utc)
        row = DataSourceModel(
            id=data_source_id,
            name=draft.name.strip(),
            connection_url=draft.connection_url.strip(),
            username=draft.username.strip() if draft.username else None,
            selected_database=draft.selected_database.strip(),
            schema_name=draft.schema.strip() if draft.schema else None,
            dialect=draft.dialect.value,
            ssl_mode=draft.ssl_mode.value,
            state=DataSourceState.DRAFT.value,
            current_revision=0,
            secret_ref=secret_ref,
            allowed_objects=list(draft.allowed_objects),
            allowed_schemas=list(draft.allowed_schemas),
            query_timeout_seconds=draft.query_timeout_seconds,
            max_rows=draft.max_rows,
            allow_private_network=draft.allow_private_network,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return self._record(row)

    def update(
        self, data_source_id: str, draft: DataSourceDraft, secret_ref: str | None
    ) -> DataSourceRecord:
        row = self._require(data_source_id)
        row.name = draft.name.strip()
        row.connection_url = draft.connection_url.strip()
        row.username = draft.username.strip() if draft.username else None
        row.selected_database = draft.selected_database.strip()
        row.schema_name = draft.schema.strip() if draft.schema else None
        row.dialect = draft.dialect.value
        row.ssl_mode = draft.ssl_mode.value
        row.secret_ref = secret_ref
        row.allowed_objects = list(draft.allowed_objects)
        row.allowed_schemas = list(draft.allowed_schemas)
        row.query_timeout_seconds = draft.query_timeout_seconds
        row.max_rows = draft.max_rows
        row.allow_private_network = draft.allow_private_network
        row.state = DataSourceState.DRAFT.value
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return self._record(row)

    def set_state(self, data_source_id: str, state: str) -> DataSourceRecord:
        row = self._require(data_source_id)
        row.state = DataSourceState(state).value
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return self._record(row)

    def save_schema_snapshot(self, snapshot: SchemaSnapshot) -> SchemaSnapshot:
        row = SchemaSnapshotModel(
            id=snapshot.id,
            data_source_id=snapshot.data_source_id,
            fingerprint=snapshot.fingerprint,
            objects=list(snapshot.objects),
            columns={key: list(value) for key, value in snapshot.columns.items()},
            captured_at=snapshot.captured_at,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot

    def get_schema_snapshot(self, snapshot_id: str) -> SchemaSnapshot | None:
        row = self._session.get(SchemaSnapshotModel, snapshot_id)
        if row is None:
            return None
        return SchemaSnapshot(
            id=row.id,
            data_source_id=row.data_source_id,
            fingerprint=row.fingerprint,
            objects=tuple(row.objects),
            columns={key: tuple(value) for key, value in row.columns.items()},
            captured_at=row.captured_at,
        )

    def create_revision(
        self,
        record: DataSourceRecord,
        actor_id: str,
        schema_snapshot_id: str | None,
    ) -> DataSourceRevision:
        source = self._require(record.id)
        source.current_revision += 1
        source.updated_at = datetime.now(timezone.utc)
        row = DataSourceRevisionModel(
            id=new_id("dsrev"),
            data_source_id=source.id,
            revision=source.current_revision,
            connection_url=source.connection_url,
            username=source.username,
            selected_database=source.selected_database,
            schema_name=source.schema_name,
            dialect=source.dialect,
            ssl_mode=source.ssl_mode,
            secret_ref=source.secret_ref,
            allowed_objects=list(source.allowed_objects),
            allowed_schemas=list(source.allowed_schemas),
            query_timeout_seconds=source.query_timeout_seconds,
            max_rows=source.max_rows,
            allow_private_network=source.allow_private_network,
            schema_snapshot_id=schema_snapshot_id,
            created_by=actor_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._revision(row)

    def get_revision(self, revision_id: str) -> DataSourceRevision | None:
        row = self._session.get(DataSourceRevisionModel, revision_id)
        return self._revision(row) if row else None

    def list_revisions(self, data_source_id: str) -> builtins.list[DataSourceRevision]:
        rows = self._session.scalars(
            select(DataSourceRevisionModel)
            .where(DataSourceRevisionModel.data_source_id == data_source_id)
            .order_by(DataSourceRevisionModel.revision.desc())
        ).all()
        return [self._revision(row) for row in rows]

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
    ) -> DomainBinding:
        current = self._session.scalars(
            select(DomainBindingModel).where(
                DomainBindingModel.domain_id == domain_id,
                DomainBindingModel.active.is_(True),
            )
        ).all()
        for row in current:
            row.active = False
        row = DomainBindingModel(
            id=binding_id,
            domain_id=domain_id,
            lab_id=lab_id,
            data_source_id=revision.data_source_id,
            data_source_revision_id=revision.id,
            allowed_objects=list(allowed_objects),
            allowed_schemas=list(allowed_schemas),
            allowed_join_keys=list(allowed_join_keys),
            active=True,
            created_by=actor_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._binding(row)

    def list_bindings(self) -> builtins.list[DomainBinding]:
        rows = self._session.scalars(
            select(DomainBindingModel).order_by(DomainBindingModel.created_at.desc())
        ).all()
        return [self._binding(row) for row in rows]

    def get_active_binding(self, domain_id: str) -> DomainBinding | None:
        row = self._session.scalar(
            select(DomainBindingModel)
            .where(DomainBindingModel.domain_id == domain_id, DomainBindingModel.active.is_(True))
            .order_by(DomainBindingModel.created_at.desc())
        )
        return self._binding(row) if row else None

    def current_domain_policy_fingerprint(
        self,
        domain_id: str,
        data_source_revision_id: str,
    ) -> str | None:
        binding = self.get_active_binding(domain_id)
        if binding is None or binding.data_source_revision_id != data_source_revision_id:
            return None
        return binding.policy_fingerprint

    def list_labs(self) -> builtins.list[SourceLab]:
        rows = self._session.scalars(select(SourceLabModel).order_by(SourceLabModel.created_at)).all()
        return [self._lab(row) for row in rows]

    def list_labs_for_source(self, data_source_id: str) -> builtins.list[SourceLab]:
        rows = self._session.scalars(
            select(SourceLabModel)
            .where(SourceLabModel.data_source_id == data_source_id)
            .order_by(SourceLabModel.created_at)
        ).all()
        return [self._lab(row) for row in rows]

    def get_lab(self, lab_row_id: str) -> SourceLab | None:
        row = self._session.get(SourceLabModel, lab_row_id)
        return self._lab(row) if row else None

    def get_lab_by_lab_id(self, lab_id: str) -> SourceLab | None:
        row = self._session.scalar(select(SourceLabModel).where(SourceLabModel.lab_id == lab_id))
        return self._lab(row) if row else None

    def upsert_lab(self, lab: SourceLab) -> SourceLab:
        row = self._session.get(SourceLabModel, lab.id)
        if row is None:
            by_key = self._session.scalar(
                select(SourceLabModel).where(SourceLabModel.lab_id == lab.lab_id)
            )
            if by_key is None:
                row = SourceLabModel(
                    id=lab.id,
                    data_source_id=lab.data_source_id,
                    lab_id=lab.lab_id,
                    name=lab.name,
                    token_secret_ref=lab.token_secret_ref,
                    created_by=lab.created_by,
                    created_at=lab.created_at,
                )
                self._session.add(row)
            else:
                row = by_key
                row.data_source_id = lab.data_source_id
                row.name = lab.name
                row.token_secret_ref = lab.token_secret_ref
        else:
            row.data_source_id = lab.data_source_id
            row.name = lab.name
            row.token_secret_ref = lab.token_secret_ref
        self._session.flush()
        return self._lab(row)

    def delete_lab(self, lab_row_id: str) -> None:
        row = self._session.get(SourceLabModel, lab_row_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    def deactivate_bindings_for_source(self, data_source_id: str) -> int:
        rows = self._session.scalars(
            select(DomainBindingModel).where(
                DomainBindingModel.data_source_id == data_source_id,
                DomainBindingModel.active.is_(True),
            )
        ).all()
        for row in rows:
            row.active = False
        self._session.flush()
        return len(rows)

    def _require(self, data_source_id: str) -> DataSourceModel:
        row = self._session.get(DataSourceModel, data_source_id)
        if row is None:
            raise LookupError(data_source_id)
        return row

    @staticmethod
    def _record(row: DataSourceModel) -> DataSourceRecord:
        return DataSourceRecord(
            id=row.id,
            name=row.name,
            connection_url=row.connection_url,
            username=row.username,
            selected_database=row.selected_database,
            schema=row.schema_name,
            dialect=DataSourceDialect(row.dialect),
            ssl_mode=DataSourceSslMode(row.ssl_mode),
            state=DataSourceState(row.state),
            current_revision=row.current_revision,
            secret_ref=row.secret_ref,
            allowed_objects=tuple(row.allowed_objects),
            allowed_schemas=tuple(row.allowed_schemas),
            query_timeout_seconds=row.query_timeout_seconds,
            max_rows=row.max_rows,
            allow_private_network=row.allow_private_network,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _revision(row: DataSourceRevisionModel) -> DataSourceRevision:
        return DataSourceRevision(
            id=row.id,
            data_source_id=row.data_source_id,
            revision=row.revision,
            connection_url=row.connection_url,
            username=row.username,
            selected_database=row.selected_database,
            schema=row.schema_name,
            dialect=DataSourceDialect(row.dialect),
            ssl_mode=DataSourceSslMode(row.ssl_mode),
            secret_ref=row.secret_ref,
            allowed_objects=tuple(row.allowed_objects),
            allowed_schemas=tuple(row.allowed_schemas),
            query_timeout_seconds=row.query_timeout_seconds,
            max_rows=row.max_rows,
            allow_private_network=row.allow_private_network,
            schema_snapshot_id=row.schema_snapshot_id,
            created_by=row.created_by,
            created_at=row.created_at,
        )

    @staticmethod
    def _lab(row: SourceLabModel) -> SourceLab:
        return SourceLab(
            id=row.id,
            data_source_id=row.data_source_id,
            lab_id=row.lab_id,
            name=row.name,
            token_secret_ref=row.token_secret_ref,
            created_by=row.created_by,
            created_at=row.created_at,
        )

    @staticmethod
    def _binding(row: DomainBindingModel) -> DomainBinding:
        return DomainBinding(
            id=row.id,
            domain_id=row.domain_id,
            lab_id=row.lab_id,
            data_source_id=row.data_source_id,
            data_source_revision_id=row.data_source_revision_id,
            allowed_objects=tuple(row.allowed_objects),
            allowed_schemas=tuple(row.allowed_schemas),
            allowed_join_keys=tuple(row.allowed_join_keys),
            active=row.active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


class SqlAlchemyAuditSink:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self, *, actor_id: str, action: str, resource_id: str, metadata: dict[str, object]
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=new_id("audit"),
                actor_id=actor_id,
                action=action,
                resource_id=resource_id,
                event_metadata=metadata,
            )
        )
        self._session.flush()
