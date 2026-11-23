"""Administrator-only data-source and domain-binding control plane."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.exc import IntegrityError

from xiaoying_quick.api.dependencies import (
    DataSourceRepositoryDep,
    DataSourceServiceDep,
    get_settings,
    require_roles,
)
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.secrets.fernet_store import SecretStoreError
from xiaoying_quick.modules.data_sources.connection_policy import UnsafeConnectionTarget
from xiaoying_quick.modules.data_sources.contracts import (
    ConnectionTestResult,
    DataSourceDialect,
    DataSourceDraft,
    DataSourceRevision,
    DataSourceSslMode,
    DataSourceState,
    DataSourceView,
    DomainBinding,
    SchemaSnapshot,
)
from xiaoying_quick.modules.data_sources.service import (
    DataSourceNotFound,
    DataSourceService,
    DataSourceValidationError,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.knowledge import list_lab_documents, match_lab_document
from xiaoying_quick.shared.errors import ApplicationError, Conflict, NotFound, ValidationFailed

router = APIRouter(prefix="/api/v2/admin", tags=["data-source-admin"])
AdminPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(Role.ADMIN, Role.DATA_SOURCE_ADMIN)),
]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class DataSourceRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=160)
    connection_url: str = Field(min_length=1, max_length=2048)
    username: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = None
    selected_database: str = Field(min_length=1, max_length=255)
    schema_name: str | None = Field(default=None, alias="schema", max_length=255)
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode = DataSourceSslMode.DISABLE
    allowed_objects: list[str] = Field(default_factory=list, max_length=1000)
    allowed_schemas: list[str] = Field(default_factory=list, max_length=100)
    query_timeout_seconds: int = Field(default=15, ge=1, le=120)
    max_rows: int = Field(default=2000, ge=1, le=10_000)
    allow_private_network: bool = False

    def to_draft(self) -> DataSourceDraft:
        return DataSourceDraft(
            name=self.name,
            connection_url=self.connection_url,
            username=self.username,
            password=self.password.get_secret_value() if self.password else None,
            selected_database=self.selected_database,
            schema=self.schema_name,
            dialect=self.dialect,
            ssl_mode=self.ssl_mode,
            allowed_objects=tuple(self.allowed_objects),
            allowed_schemas=tuple(self.allowed_schemas),
            query_timeout_seconds=self.query_timeout_seconds,
            max_rows=self.max_rows,
            allow_private_network=self.allow_private_network,
        )


class RotateCredentialRequest(StrictRequest):
    password: SecretStr


class LabAttachRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=160)
    token: SecretStr


class DomainBindingRequest(StrictRequest):
    domain_id: Literal["actual", "demand", "ext_simple", "ext_complex"]
    lab_id: Literal["actual", "demand", "ext_simple", "ext_complex"]
    revision_id: str = Field(min_length=1, max_length=64)
    allowed_objects: list[str] = Field(min_length=1, max_length=1000)
    allowed_schemas: list[str] = Field(default_factory=list, max_length=100)
    allowed_join_keys: list[str] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def domain_and_lab_must_match(self) -> DomainBindingRequest:
        if self.domain_id != self.lab_id:
            raise ValueError("Quick 域必须绑定同名实验室")
        return self


class LabDocumentResponse(BaseModel):
    lab_id: str
    name: str
    path: str
    blurb: str


class LabAttachmentResponse(BaseModel):
    id: str
    lab_id: str
    name: str
    document: str | None = None
    blurb: str = ""
    token_configured: bool


class DataSourceResponse(BaseModel):
    id: str
    name: str
    connection_url: str
    username: str | None
    selected_database: str
    schema_name: str | None = Field(serialization_alias="schema")
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode
    state: DataSourceState
    current_revision: int
    credential_configured: bool
    allowed_objects: list[str]
    allowed_schemas: list[str]
    query_timeout_seconds: int
    max_rows: int
    allow_private_network: bool
    created_at: datetime
    updated_at: datetime
    labs: list[LabAttachmentResponse] = Field(default_factory=list)


class SchemaSnapshotResponse(BaseModel):
    id: str
    fingerprint: str
    objects: list[str]
    columns: dict[str, list[str]]
    captured_at: datetime


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    database: str | None
    server_version: str | None
    read_only: bool | None
    schema_snapshot: SchemaSnapshotResponse | None
    errors: list[str]


class DataSourceRevisionResponse(BaseModel):
    id: str
    data_source_id: str
    revision: int
    selected_database: str
    schema_name: str | None = Field(serialization_alias="schema")
    dialect: DataSourceDialect
    ssl_mode: DataSourceSslMode
    credential_configured: bool
    allowed_objects: list[str]
    allowed_schemas: list[str]
    query_timeout_seconds: int
    max_rows: int
    schema_snapshot_id: str | None
    created_by: str
    created_at: datetime


class DomainBindingResponse(BaseModel):
    id: str
    domain_id: str
    lab_id: str
    data_source_id: str
    data_source_revision_id: str
    allowed_objects: list[str]
    allowed_schemas: list[str]
    allowed_join_keys: list[str]
    active: bool
    created_by: str
    created_at: datetime


T = TypeVar("T")


def _translate(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (DataSourceNotFound, LookupError) as exc:
        raise NotFound("data source or revision not found") from exc
    except IntegrityError as exc:
        raise Conflict("data-source configuration conflicts with an existing record") from exc
    except SecretStoreError as exc:
        raise ApplicationError("encrypted secret store operation failed") from exc
    except (DataSourceValidationError, UnsafeConnectionTarget, ValueError) as exc:
        raise ValidationFailed(str(exc)) from exc


def _view(
    value: DataSourceView,
    labs: list[LabAttachmentResponse] | None = None,
) -> DataSourceResponse:
    return DataSourceResponse(
        id=value.id,
        name=value.name,
        connection_url=value.connection_url,
        username=value.username,
        selected_database=value.selected_database,
        schema_name=value.schema,
        dialect=value.dialect,
        ssl_mode=value.ssl_mode,
        state=value.state,
        current_revision=value.current_revision,
        credential_configured=value.credential_configured,
        allowed_objects=list(value.allowed_objects),
        allowed_schemas=list(value.allowed_schemas),
        query_timeout_seconds=value.query_timeout_seconds,
        max_rows=value.max_rows,
        allow_private_network=value.allow_private_network,
        created_at=value.created_at,
        updated_at=value.updated_at,
        labs=labs or [],
    )


def _env_lab_ids(settings: Settings) -> set[str]:
    return {
        lab_id
        for lab_id, secret in (
            ("actual", settings.lab_actual_token),
            ("demand", settings.lab_demand_token),
            ("ext_simple", settings.lab_ext_simple_token),
            ("ext_complex", settings.lab_ext_complex_token),
        )
        if secret is not None
    }


def _labs_for_source(
    source_id: str,
    service: DataSourceService,
    settings: Settings,
) -> list[LabAttachmentResponse]:
    documents = {item.lab_id: item for item in list_lab_documents(settings.knowledge_root)}
    env_ids = _env_lab_ids(settings)
    payload: list[LabAttachmentResponse] = []
    seen: set[str] = set()
    for lab in service.list_labs_for_source(source_id):
        seen.add(lab.lab_id)
        document = documents.get(lab.lab_id)
        payload.append(
            LabAttachmentResponse(
                id=lab.id,
                lab_id=lab.lab_id,
                name=lab.name,
                document=document.path if document else None,
                blurb=document.blurb if document else "",
                token_configured=True,
            )
        )
    for binding in service.list_bindings():
        if not binding.active or binding.data_source_id != source_id or binding.lab_id in seen:
            continue
        document = documents.get(binding.lab_id)
        payload.append(
            LabAttachmentResponse(
                id=binding.id,
                lab_id=binding.lab_id,
                name=document.name if document else binding.lab_id,
                document=document.path if document else None,
                blurb=document.blurb if document else "",
                token_configured=binding.lab_id in env_ids,
            )
        )
    return payload


def _test_result(value: ConnectionTestResult) -> ConnectionTestResponse:
    snapshot = _snapshot(value.schema_snapshot) if value.schema_snapshot else None
    return ConnectionTestResponse(
        ok=value.ok,
        latency_ms=value.latency_ms,
        database=value.database,
        server_version=value.server_version,
        read_only=value.read_only,
        schema_snapshot=snapshot,
        errors=list(value.errors),
    )


def _snapshot(value: SchemaSnapshot) -> SchemaSnapshotResponse:
    return SchemaSnapshotResponse(
        id=value.id,
        fingerprint=value.fingerprint,
        objects=list(value.objects),
        columns={name: list(columns) for name, columns in value.columns.items()},
        captured_at=value.captured_at,
    )


def _revision(value: DataSourceRevision) -> DataSourceRevisionResponse:
    return DataSourceRevisionResponse(
        id=value.id,
        data_source_id=value.data_source_id,
        revision=value.revision,
        selected_database=value.selected_database,
        schema_name=value.schema,
        dialect=value.dialect,
        ssl_mode=value.ssl_mode,
        credential_configured=bool(value.secret_ref),
        allowed_objects=list(value.allowed_objects),
        allowed_schemas=list(value.allowed_schemas),
        query_timeout_seconds=value.query_timeout_seconds,
        max_rows=value.max_rows,
        schema_snapshot_id=value.schema_snapshot_id,
        created_by=value.created_by,
        created_at=value.created_at,
    )


def _binding(value: DomainBinding) -> DomainBindingResponse:
    return DomainBindingResponse(
        id=value.id,
        domain_id=value.domain_id,
        lab_id=value.lab_id,
        data_source_id=value.data_source_id,
        data_source_revision_id=value.data_source_revision_id,
        allowed_objects=list(value.allowed_objects),
        allowed_schemas=list(value.allowed_schemas),
        allowed_join_keys=list(value.allowed_join_keys),
        active=value.active,
        created_by=value.created_by,
        created_at=value.created_at,
    )


@router.get("/lab-documents", response_model=list[LabDocumentResponse])
def get_lab_documents(settings: SettingsDep, _admin: AdminPrincipal) -> list[LabDocumentResponse]:
    return [
        LabDocumentResponse(
            lab_id=item.lab_id, name=item.name, path=item.path, blurb=item.blurb
        )
        for item in list_lab_documents(settings.knowledge_root)
    ]


@router.get("/data-sources", response_model=list[DataSourceResponse])
def list_data_sources(
    service: DataSourceServiceDep, settings: SettingsDep, _admin: AdminPrincipal
) -> list[DataSourceResponse]:
    return [
        _view(record.as_view(), _labs_for_source(record.id, service, settings))
        for record in _translate(service.list)
    ]


@router.post(
    "/data-sources",
    response_model=DataSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_data_source(
    body: DataSourceRequest,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceResponse:
    record = _translate(lambda: service.create(body.to_draft(), admin.user_id))
    return _view(record.as_view())


@router.get("/data-sources/{data_source_id}", response_model=DataSourceResponse)
def get_data_source(
    data_source_id: str,
    service: DataSourceServiceDep,
    settings: SettingsDep,
    _admin: AdminPrincipal,
) -> DataSourceResponse:
    record = _translate(lambda: service.get(data_source_id))
    return _view(record.as_view(), _labs_for_source(record.id, service, settings))


@router.get(
    "/data-sources/{data_source_id}/revisions",
    response_model=list[DataSourceRevisionResponse],
)
def list_data_source_revisions(
    data_source_id: str,
    service: DataSourceServiceDep,
    repository: DataSourceRepositoryDep,
    _admin: AdminPrincipal,
) -> list[DataSourceRevisionResponse]:
    _translate(lambda: service.get(data_source_id))
    return [
        _revision(value) for value in _translate(lambda: repository.list_revisions(data_source_id))
    ]


@router.put("/data-sources/{data_source_id}", response_model=DataSourceResponse)
def update_data_source(
    data_source_id: str,
    body: DataSourceRequest,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceResponse:
    record = _translate(lambda: service.update(data_source_id, body.to_draft(), admin.user_id))
    return _view(record.as_view())


@router.post("/data-sources/{data_source_id}/test", response_model=ConnectionTestResponse)
def test_data_source(
    data_source_id: str,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> ConnectionTestResponse:
    return _test_result(_translate(lambda: service.test(data_source_id, admin.user_id)))


@router.post(
    "/data-sources/{data_source_id}/activate",
    response_model=DataSourceRevisionResponse,
)
def activate_data_source(
    data_source_id: str,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceRevisionResponse:
    return _revision(_translate(lambda: service.activate(data_source_id, admin.user_id)))


@router.post("/data-sources/{data_source_id}/disable", response_model=DataSourceResponse)
def disable_data_source(
    data_source_id: str,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceResponse:
    record = _translate(lambda: service.disable(data_source_id, admin.user_id))
    return _view(record.as_view())


@router.delete("/data-sources/{data_source_id}", response_model=DataSourceResponse)
def delete_data_source(
    data_source_id: str,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceResponse:
    """Soft-delete by disabling; immutable revisions and audit history remain."""

    record = _translate(lambda: service.disable(data_source_id, admin.user_id))
    return _view(record.as_view())


@router.post(
    "/data-sources/{data_source_id}/labs",
    response_model=LabAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def attach_lab(
    data_source_id: str,
    body: LabAttachRequest,
    service: DataSourceServiceDep,
    settings: SettingsDep,
    admin: AdminPrincipal,
) -> LabAttachmentResponse:
    document = match_lab_document(settings.knowledge_root, body.name)
    if document is None:
        raise ValidationFailed(f"没有找到对应的实验室文档：{body.name}")
    lab = _translate(
        lambda: service.attach_lab(
            data_source_id,
            lab_id=document.lab_id,
            name=document.name,
            token=body.token.get_secret_value(),
            actor_id=admin.user_id,
        )
    )
    return LabAttachmentResponse(
        id=lab.id,
        lab_id=lab.lab_id,
        name=lab.name,
        document=document.path,
        blurb=document.blurb,
        token_configured=True,
    )


@router.delete("/data-sources/{data_source_id}/labs/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach_lab(
    data_source_id: str,
    lab_id: str,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> None:
    _translate(lambda: service.detach_lab(data_source_id, lab_id, admin.user_id))


@router.post(
    "/data-sources/{data_source_id}/rotate",
    response_model=DataSourceResponse,
)
@router.post(
    "/data-sources/{data_source_id}/rotate-credential",
    response_model=DataSourceResponse,
    include_in_schema=False,
)
def rotate_data_source_credential(
    data_source_id: str,
    body: RotateCredentialRequest,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DataSourceResponse:
    record = _translate(
        lambda: service.rotate_credential(
            data_source_id, body.password.get_secret_value(), admin.user_id
        )
    )
    return _view(record.as_view())


@router.get("/domain-bindings", response_model=list[DomainBindingResponse])
def list_domain_bindings(
    repository: DataSourceRepositoryDep, _admin: AdminPrincipal
) -> list[DomainBindingResponse]:
    return [_binding(value) for value in _translate(repository.list_bindings)]


@router.post(
    "/domain-bindings",
    response_model=DomainBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
def bind_domain(
    body: DomainBindingRequest,
    repository: DataSourceRepositoryDep,
    service: DataSourceServiceDep,
    admin: AdminPrincipal,
) -> DomainBindingResponse:
    revision = _translate(lambda: repository.get_revision(body.revision_id))
    if revision is None:
        raise NotFound("data source revision not found")
    source = _translate(lambda: service.get(revision.data_source_id))
    if source.state is not DataSourceState.ACTIVE:
        raise ValidationFailed("only an active data source can be bound to a domain")
    if revision.revision != source.current_revision:
        raise ValidationFailed("only the current active revision can be bound")
    value = _translate(
        lambda: service.bind_domain(
            domain_id=body.domain_id,
            lab_id=body.lab_id,
            revision_id=body.revision_id,
            actor_id=admin.user_id,
            allowed_objects=tuple(body.allowed_objects),
            allowed_schemas=tuple(body.allowed_schemas),
            allowed_join_keys=tuple(body.allowed_join_keys),
        )
    )
    return _binding(value)
