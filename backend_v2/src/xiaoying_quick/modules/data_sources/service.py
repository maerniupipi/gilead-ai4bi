from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from xiaoying_quick.shared.ids import new_id

from .connection_policy import ConnectionPolicy
from .contracts import (
    ConnectionTestResult,
    DataSourceDraft,
    DataSourceRecord,
    DataSourceRevision,
    DataSourceState,
    DomainBinding,
    SourceLab,
)
from .ports import ConnectionProbe, DataSourceAuditSink, DataSourceRepository, SecretStore


class DataSourceNotFound(LookupError):
    pass


class DataSourceValidationError(ValueError):
    pass


class DataSourceService:
    def __init__(
        self,
        repository: DataSourceRepository,
        secrets: SecretStore,
        probe: ConnectionProbe,
        audit: DataSourceAuditSink,
        policy: ConnectionPolicy,
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._secrets = secrets
        self._probe = probe
        self._audit = audit
        self._policy = policy
        self._id_factory = id_factory

    def list(self) -> list[DataSourceRecord]:
        return self._repository.list()

    def get(self, data_source_id: str) -> DataSourceRecord:
        record = self._repository.get(data_source_id)
        if record is None:
            raise DataSourceNotFound(data_source_id)
        return record

    def create(self, draft: DataSourceDraft, actor_id: str) -> DataSourceRecord:
        self._validate(draft, require_password=draft.dialect.value != "sqlite")
        secret_ref = self._secrets.put(draft.password) if draft.password else None
        safe_draft = replace(draft, password=None)
        try:
            record = self._repository.create(self._id_factory(), safe_draft, secret_ref)
        except Exception:
            if secret_ref:
                self._secrets.delete(secret_ref)
            raise
        self._audit.record(
            actor_id=actor_id, action="data_source.created", resource_id=record.id, metadata={}
        )
        return record

    def update(
        self, data_source_id: str, draft: DataSourceDraft, actor_id: str
    ) -> DataSourceRecord:
        current = self.get(data_source_id)
        self._validate(draft, require_password=False)
        secret_ref = current.secret_ref
        new_secret_ref = None
        if draft.password:
            # Revisions are immutable execution inputs. Never overwrite the
            # credential referenced by an earlier activated revision.
            new_secret_ref = self._secrets.put(draft.password)
            secret_ref = new_secret_ref
        safe_draft = replace(draft, password=None)
        try:
            record = self._repository.update(data_source_id, safe_draft, secret_ref)
            deactivated = self._repository.deactivate_bindings_for_source(data_source_id)
            self._audit.record(
                actor_id=actor_id,
                action="data_source.updated",
                resource_id=record.id,
                metadata={"deactivated_bindings": deactivated},
            )
        except Exception:
            if new_secret_ref:
                self._secrets.delete(new_secret_ref)
            raise
        return record

    def rotate_credential(
        self, data_source_id: str, password: str, actor_id: str
    ) -> DataSourceRecord:
        if not password:
            raise DataSourceValidationError("密码不能为空")
        current = self.get(data_source_id)
        secret_ref = self._secrets.put(password)
        draft = DataSourceDraft(
            name=current.name,
            connection_url=current.connection_url,
            username=current.username,
            password=None,
            selected_database=current.selected_database,
            schema=current.schema,
            dialect=current.dialect,
            ssl_mode=current.ssl_mode,
            allowed_objects=current.allowed_objects,
            allowed_schemas=current.allowed_schemas,
            query_timeout_seconds=current.query_timeout_seconds,
            max_rows=current.max_rows,
            allow_private_network=current.allow_private_network,
        )
        try:
            record = self._repository.update(data_source_id, draft, secret_ref)
            deactivated = self._repository.deactivate_bindings_for_source(data_source_id)
            self._audit.record(
                actor_id=actor_id,
                action="data_source.credential_rotated",
                resource_id=record.id,
                metadata={"deactivated_bindings": deactivated},
            )
        except Exception:
            self._secrets.delete(secret_ref)
            raise
        return record

    def probe_draft(
        self, draft: DataSourceDraft, *, source_id: str | None = None
    ) -> ConnectionTestResult:
        """Test a not-yet-saved connection and return the live table list."""

        password = draft.password
        if not password and source_id:
            current = self.get(source_id)
            password = self._secrets.get(current.secret_ref) if current.secret_ref else None
            draft = replace(draft, password=password)
        self._validate(draft, require_password=draft.dialect.value != "sqlite")
        revision = DataSourceRevision(
            id="probe",
            data_source_id="probe",
            revision=0,
            connection_url=draft.connection_url,
            username=draft.username,
            selected_database=draft.selected_database,
            schema=draft.schema,
            dialect=draft.dialect,
            ssl_mode=draft.ssl_mode,
            secret_ref=None,
            allowed_objects=draft.allowed_objects,
            allowed_schemas=draft.allowed_schemas,
            query_timeout_seconds=draft.query_timeout_seconds,
            max_rows=draft.max_rows,
            allow_private_network=draft.allow_private_network,
            schema_snapshot_id=None,
            created_by="probe",
            created_at=datetime.now(timezone.utc),
        )
        return self._probe.test(revision, draft.password)

    def test(self, data_source_id: str, actor_id: str) -> ConnectionTestResult:
        current = self.get(data_source_id)
        revision = self._ephemeral_revision(current, actor_id)
        password = self._secrets.get(current.secret_ref) if current.secret_ref else None
        result = self._probe.test(revision, password)
        self._audit.record(
            actor_id=actor_id,
            action="data_source.connection_tested",
            resource_id=current.id,
            metadata={"ok": result.ok, "latency_ms": result.latency_ms},
        )
        return result

    def activate(self, data_source_id: str, actor_id: str) -> DataSourceRevision:
        current = self.get(data_source_id)
        result = self.test(data_source_id, actor_id)
        if not result.ok or result.read_only is False:
            raise DataSourceValidationError("连接或只读检查未通过，不能激活")
        snapshot_id = None
        if result.schema_snapshot is not None:
            snapshot_id = self._repository.save_schema_snapshot(result.schema_snapshot).id
            if not current.allowed_objects:
                current = self._repository.update(
                    current.id,
                    DataSourceDraft(
                        name=current.name,
                        connection_url=current.connection_url,
                        username=current.username,
                        password=None,
                        selected_database=current.selected_database,
                        schema=current.schema,
                        dialect=current.dialect,
                        ssl_mode=current.ssl_mode,
                        allowed_objects=result.schema_snapshot.objects,
                        allowed_schemas=current.allowed_schemas,
                        query_timeout_seconds=current.query_timeout_seconds,
                        max_rows=current.max_rows,
                        allow_private_network=current.allow_private_network,
                    ),
                    current.secret_ref,
                )
        restore_ids = self._lab_ids_for_source(current.id)
        active = self._repository.set_state(current.id, DataSourceState.ACTIVE.value)
        revision = self._repository.create_revision(active, actor_id, snapshot_id)
        deactivated = self._repository.deactivate_bindings_for_source(current.id)
        rebound = self._bind_labs(active, revision, actor_id, restore_ids)
        self._audit.record(
            actor_id=actor_id,
            action="data_source.activated",
            resource_id=current.id,
            metadata={
                "revision_id": revision.id,
                "revision": revision.revision,
                "deactivated_bindings": deactivated,
                "rebound_labs": rebound,
            },
        )
        return revision

    def disable(self, data_source_id: str, actor_id: str) -> DataSourceRecord:
        record = self._repository.set_state(data_source_id, DataSourceState.DISABLED.value)
        deactivated = self._repository.deactivate_bindings_for_source(data_source_id)
        self._audit.record(
            actor_id=actor_id,
            action="data_source.disabled",
            resource_id=record.id,
            metadata={"deactivated_bindings": deactivated},
        )
        return record

    def bind_domain(
        self,
        *,
        domain_id: str,
        lab_id: str,
        revision_id: str,
        actor_id: str,
        allowed_objects: tuple[str, ...],
        allowed_schemas: tuple[str, ...] = (),
        allowed_join_keys: tuple[str, ...] = (),
    ) -> DomainBinding:
        revision = self._repository.get_revision(revision_id)
        if revision is None:
            raise DataSourceNotFound(revision_id)
        source = self.get(revision.data_source_id)
        if source.state is not DataSourceState.ACTIVE:
            raise DataSourceValidationError("只有已激活的数据源可以绑定域")
        if source.current_revision != revision.revision:
            raise DataSourceValidationError("只有当前激活版本可以绑定域")
        objects = self._binding_identifiers(allowed_objects, "对象")
        schemas = self._binding_identifiers(allowed_schemas, "schema", allow_empty=True)
        revision_objects = frozenset(
            self._normalize_identifier(value) for value in revision.allowed_objects
        )
        revision_schemas = frozenset(
            self._normalize_identifier(value) for value in revision.allowed_schemas
        )
        if not set(objects).issubset(revision_objects):
            raise DataSourceValidationError("域对象白名单必须是数据源版本白名单的子集")
        if not set(schemas).issubset(revision_schemas):
            raise DataSourceValidationError("域 schema 白名单必须是数据源版本白名单的子集")
        try:
            join_keys = tuple(sorted({_normalize_join_key(value) for value in allowed_join_keys}))
        except ValueError as exc:
            raise DataSourceValidationError(str(exc)) from exc
        object_set = set(objects)
        for join_key in join_keys:
            endpoints = join_key.split("=")
            if any(self._join_object(endpoint) not in object_set for endpoint in endpoints):
                raise DataSourceValidationError("域 join key 只能引用域对象白名单中的对象")
        binding = self._repository.bind_domain(
            self._id_factory(),
            domain_id,
            lab_id,
            revision,
            actor_id,
            objects,
            schemas,
            join_keys,
        )
        self._audit.record(
            actor_id=actor_id,
            action="domain_binding.activated",
            resource_id=binding.id,
            metadata={
                "domain_id": domain_id,
                "revision_id": revision_id,
                "policy_fingerprint": binding.policy_fingerprint,
            },
        )
        return binding

    def list_bindings(self) -> list[DomainBinding]:
        return self._repository.list_bindings()

    def list_labs(self) -> list[SourceLab]:
        return self._repository.list_labs()

    def list_labs_for_source(self, data_source_id: str) -> list[SourceLab]:
        self.get(data_source_id)
        return self._repository.list_labs_for_source(data_source_id)

    def attach_lab(
        self,
        data_source_id: str,
        *,
        lab_id: str,
        name: str,
        token: str,
        actor_id: str,
    ) -> SourceLab:
        source = self.get(data_source_id)
        clean_token = _validate_lab_token(token)
        existing = self._repository.get_lab_by_lab_id(lab_id)
        if existing is not None and existing.data_source_id != data_source_id:
            raise DataSourceValidationError(f"「{name}」已绑定到其他数据源")
        if source.state is not DataSourceState.ACTIVE:
            self.activate(data_source_id, actor_id)
            source = self.get(data_source_id)
        revision = self._current_revision(source)
        if revision is None:
            raise DataSourceValidationError("请先启用数据源")
        objects = source.allowed_objects
        if not objects:
            raise DataSourceValidationError("请先测试连接，系统会带出默认可查询对象")
        secret_ref = self._secrets.put(
            clean_token,
            current_ref=existing.token_secret_ref if existing else None,
        )
        lab = SourceLab(
            id=existing.id if existing else new_id("slab"),
            data_source_id=source.id,
            lab_id=lab_id,
            name=name,
            token_secret_ref=secret_ref,
            created_by=existing.created_by if existing else actor_id,
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
        )
        saved = self._repository.upsert_lab(lab)
        self.bind_domain(
            domain_id=lab_id,
            lab_id=lab_id,
            revision_id=revision.id,
            actor_id=actor_id,
            allowed_objects=objects,
            allowed_schemas=source.allowed_schemas,
        )
        self._audit.record(
            actor_id=actor_id,
            action="source_lab.attached",
            resource_id=saved.id,
            metadata={"lab_id": lab_id, "data_source_id": source.id},
        )
        return saved

    def detach_lab(self, data_source_id: str, lab_id: str, actor_id: str) -> None:
        source = self.get(data_source_id)
        lab = self._repository.get_lab_by_lab_id(lab_id)
        if lab is not None and lab.data_source_id != source.id:
            raise DataSourceValidationError("该实验室不属于当前数据源")
        binding = self._repository.get_active_binding(lab_id)
        belongs = (lab is not None and lab.data_source_id == source.id) or (
            binding is not None and binding.data_source_id == source.id
        )
        if not belongs:
            raise DataSourceNotFound(lab_id)
        restore = [item for item in self._lab_ids_for_source(source.id) if item != lab_id]
        if binding is not None and binding.data_source_id == source.id:
            self._repository.deactivate_bindings_for_source(source.id)
            revision = self._current_revision(source)
            if revision is not None and source.state is DataSourceState.ACTIVE:
                self._bind_labs(source, revision, actor_id, restore)
        if lab is not None:
            self._repository.delete_lab(lab.id)
            try:
                self._secrets.delete(lab.token_secret_ref)
            except Exception:
                pass
        self._audit.record(
            actor_id=actor_id,
            action="source_lab.detached",
            resource_id=lab.id if lab else lab_id,
            metadata={"lab_id": lab_id, "data_source_id": source.id},
        )

    def _current_revision(self, source: DataSourceRecord) -> DataSourceRevision | None:
        if source.current_revision <= 0:
            return None
        for revision in self._repository.list_revisions(source.id):
            if revision.revision == source.current_revision:
                return revision
        return None

    def _lab_ids_for_source(self, data_source_id: str) -> list[str]:
        ids = [lab.lab_id for lab in self._repository.list_labs_for_source(data_source_id)]
        for binding in self._repository.list_bindings():
            if binding.active and binding.data_source_id == data_source_id and binding.lab_id not in ids:
                ids.append(binding.lab_id)
        return ids

    def _bind_labs(
        self,
        source: DataSourceRecord,
        revision: DataSourceRevision,
        actor_id: str,
        lab_ids: list[str],
    ) -> list[str]:
        objects = source.allowed_objects
        if not objects:
            return []
        rebound: list[str] = []
        for lab_id in lab_ids:
            self.bind_domain(
                domain_id=lab_id,
                lab_id=lab_id,
                revision_id=revision.id,
                actor_id=actor_id,
                allowed_objects=objects,
                allowed_schemas=source.allowed_schemas,
            )
            rebound.append(lab_id)
        return rebound

    @classmethod
    def _binding_identifiers(
        cls,
        values: tuple[str, ...],
        label: str,
        *,
        allow_empty: bool = False,
    ) -> tuple[str, ...]:
        normalized = tuple(sorted({cls._normalize_identifier(value) for value in values}))
        if "" in normalized or (not normalized and not allow_empty):
            raise DataSourceValidationError(f"域{label}白名单不能为空")
        return normalized

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        return ".".join(
            part.strip().strip('`"[]').casefold()
            for part in value.strip().split(".")
            if part.strip().strip('`"[]')
        )

    @staticmethod
    def _join_object(endpoint: str) -> str:
        return endpoint.rsplit(".", 1)[0]

    def _validate(self, draft: DataSourceDraft, *, require_password: bool) -> None:
        if not draft.name.strip():
            raise DataSourceValidationError("数据源名称不能为空")
        if require_password and not draft.password:
            raise DataSourceValidationError("非 SQLite 数据源必须配置密码")
        self._policy.validate(draft)

    @staticmethod
    def _ephemeral_revision(current: DataSourceRecord, actor_id: str) -> DataSourceRevision:
        return DataSourceRevision(
            id=f"test:{current.id}:{current.current_revision}",
            data_source_id=current.id,
            revision=current.current_revision,
            connection_url=current.connection_url,
            username=current.username,
            selected_database=current.selected_database,
            schema=current.schema,
            dialect=current.dialect,
            ssl_mode=current.ssl_mode,
            secret_ref=current.secret_ref,
            allowed_objects=current.allowed_objects,
            allowed_schemas=current.allowed_schemas,
            query_timeout_seconds=current.query_timeout_seconds,
            max_rows=current.max_rows,
            allow_private_network=current.allow_private_network,
            schema_snapshot_id=None,
            created_by=actor_id,
            created_at=current.updated_at,
        )


def _validate_lab_token(token: str) -> str:
    value = (token or "").strip()
    if not value or value != token.strip() or not all(0x21 <= ord(character) <= 0x7E for character in value):
        raise DataSourceValidationError("Token 包含非法字符")
    return value


def _normalize_join_key(value: str) -> str:
    parts = value.split("=")
    if len(parts) != 2:
        raise ValueError("join key must use table.column=table.column")
    endpoints = tuple(_normalize_join_endpoint(part) for part in parts)
    if any(not endpoint or "." not in endpoint for endpoint in endpoints):
        raise ValueError("join key must use table.column=table.column")
    return "=".join(sorted(endpoints))


def _normalize_join_endpoint(value: str) -> str:
    return ".".join(
        part.strip().strip('`"[]').casefold()
        for part in value.strip().split(".")
        if part.strip().strip('`"[]')
    )
