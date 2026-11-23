"""Administrator-only catalog of registered tools and configurable agents."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from xiaoying_quick.api.dependencies import (
    DataSourceRepositoryDep,
    DataSourceServiceDep,
    DbSession,
    get_settings,
    require_roles,
)
from xiaoying_quick.application.agent_run.assembly import (
    build_primitive_tools,
    public_tool_records,
    used_by_map,
)
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.repositories.agent_configs import (
    SqlAlchemyAgentConfigRepository,
)
from xiaoying_quick.modules.agent import AgentConfigService
from xiaoying_quick.modules.data_sources.connection_policy import UnsafeConnectionTarget
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceDraft,
    DataSourceSslMode,
    DataSourceState,
)
from xiaoying_quick.modules.data_sources.service import (
    DataSourceNotFound,
    DataSourceService,
    DataSourceValidationError,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.knowledge.lab_catalog import allowed_lab_ids
from xiaoying_quick.shared.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/api/v2/admin", tags=["agent-admin"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentUpdateRequest(StrictRequest):
    enabled: bool | None = None
    tool_names: list[str] | None = Field(default=None, max_length=32)
    agent_names: list[str] | None = Field(default=None, max_length=16)
    extras: dict[str, Any] | None = None


class QueryToolConfigRequest(StrictRequest):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    source_id: str | None = Field(default=None, max_length=64)
    name: str = Field(default="智能体查询库", min_length=1, max_length=160)
    connection_url: str = Field(min_length=1, max_length=2048)
    username: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = None
    selected_database: str = Field(min_length=1, max_length=255)
    schema_name: str | None = Field(default=None, alias="schema", max_length=255)
    dialect: DataSourceDialect = DataSourceDialect.MYSQL
    ssl_mode: DataSourceSslMode = DataSourceSslMode.DISABLE
    allowed_objects: list[str] = Field(default_factory=list, max_length=1000)
    query_timeout_seconds: int = Field(default=15, ge=1, le=120)
    max_rows: int = Field(default=2000, ge=1, le=10_000)
    allow_private_network: bool = True

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
            allowed_schemas=(),
            query_timeout_seconds=self.query_timeout_seconds,
            max_rows=self.max_rows,
            allow_private_network=self.allow_private_network,
        )


def get_agent_service(session: DbSession) -> AgentConfigService:
    return AgentConfigService(SqlAlchemyAgentConfigRepository(session))


AgentServiceDep = Annotated[AgentConfigService, Depends(get_agent_service)]


def _lab_ids(settings: Settings) -> tuple[str, ...]:
    return allowed_lab_ids(settings.knowledge_root, None) or ()


def _primitives(settings: Settings):
    return build_primitive_tools(
        lab_ids=_lab_ids(settings),
        knowledge_root=settings.knowledge_root,
        max_sales_month=settings.lab_max_sales_month,
    )


@router.get("/tools", status_code=status.HTTP_200_OK)
def list_tools(
    session: DbSession,
    settings: SettingsDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    service = get_agent_service(session)
    profiles = service.list_profiles()
    used = used_by_map(profiles)
    if _paired_profile(session):
        from xiaoying_quick.application.agent_run.business_knowledge import business_knowledge_tools
        active = {"query_db","export_xlsx","ask_user","knowledge_search","knowledge_read"}
        specs = {**_primitives(settings), **{tool.name: tool for tool in business_knowledge_tools()}}
        items = [{**r,"usedBy":[{"id":"main","name":"主智能体"}]} for r in public_tool_records(specs) if r["name"] in active]
        for item in items:
            if item["name"] == "query_db":
                item["description"] = "执行本轮原子 SQL，或在这些原子结果上进行只读组合分析"
                item["parameters"] = [{"name":"sql","required":False,"text":"原子编号或引用本轮原子结果的 SELECT"}]
        for name, title, detail in (("recall_lab","召回实验室","匹配数据库字段、实际取值和别名"),
                                    ("generate_sql","生成 SQL 实验室","为一个原子问题生成 PostgreSQL 查询并返回本轮编号")):
            items.append({"name":name,"label":title,"group":"lab","description":detail,"configurable":False,"catalog_only":False,
                          "parameters":[{"name":"lab_id","required":True,"text":"已绑定的实验室组合"},{"name":"question","required":True,"text":"待解释的术语或一个完整的原子问题"}],
                          "usedBy":[{"id":"main","name":"主智能体"}]})
        return {"items":items}
    items = []
    for record in public_tool_records(_primitives(settings)):
        owners = used.get(str(record["name"]), [])
        items.append({**record, "usedBy": owners})
    return {"items": items}


def _paired_profile(session):
    from xiaoying_quick.infrastructure.persistence.models.lab_connection import LabConnectionModel
    row = session.get(LabConnectionModel, "workspace")
    return row and any(p.get("recall_api_access_id") for p in row.profiles.get("bootcamp",{}).get("labs",{}).values())


@router.get("/agents", status_code=status.HTTP_200_OK)
def list_agents(
    session: DbSession,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    items = [profile.to_public_record() for profile in get_agent_service(session).list_profiles()]
    if _paired_profile(session):
        from xiaoying_quick.infrastructure.lab_http.gilead import SYSTEM_PROMPT
        items=[{**p, "toolNames":["knowledge_search","knowledge_read","recall_lab","generate_sql","query_db","export_xlsx","ask_user"],
                "agentNames":[], "systemPrompt":SYSTEM_PROMPT, "blurb":"检索共享业务知识，通过平台实验室和只读查询完成问数"} for p in items if p["id"]=="main"]
    return {"items": items}


@router.patch("/agents/{agent_id}", status_code=status.HTTP_200_OK)
def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    session: DbSession,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    profile = get_agent_service(session).update(
        agent_id,
        enabled=body.enabled,
        tool_names=tuple(body.tool_names) if body.tool_names is not None else None,
        agent_names=tuple(body.agent_names) if body.agent_names is not None else None,
        extras=body.extras,
    )
    return profile.to_public_record()


@router.post("/agents/{agent_id}/enable", status_code=status.HTTP_200_OK)
def enable_agent(
    agent_id: str,
    session: DbSession,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    return get_agent_service(session).set_enabled(agent_id, True).to_public_record()


@router.post("/agents/{agent_id}/disable", status_code=status.HTTP_200_OK)
def disable_agent(
    agent_id: str,
    session: DbSession,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    return get_agent_service(session).set_enabled(agent_id, False).to_public_record()


QUERY_TOOL_NAME = "智能体查询库"


@router.get("/tools/query_db/config", status_code=status.HTTP_200_OK)
def get_query_tool_config(
    service: DataSourceServiceDep,
    repository: DataSourceRepositoryDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    record = _bound_query_source(service)
    if record is None:
        return {
            "source": None,
            "form": _empty_query_form(),
            "tables": [],
            "columns": {},
            "selected": [],
        }
    tables, columns = _snapshot_tables(repository, record)
    return {
        "source": {
            "id": record.id,
            "name": record.name,
            "state": record.state.value,
            "credential_configured": bool(record.secret_ref),
        },
        "form": {
            "source_id": record.id,
            "name": record.name,
            "connection_url": record.connection_url,
            "username": record.username or "",
            "selected_database": record.selected_database,
            "schema": record.schema or "",
            "dialect": record.dialect.value,
            "ssl_mode": record.ssl_mode.value,
            "query_timeout_seconds": record.query_timeout_seconds,
            "max_rows": record.max_rows,
            "allow_private_network": record.allow_private_network,
        },
        "tables": tables,
        "columns": columns,
        "selected": list(record.allowed_objects),
    }


@router.post("/tools/query_db/probe", status_code=status.HTTP_200_OK)
def probe_query_tool_config(
    body: QueryToolConfigRequest,
    service: DataSourceServiceDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    try:
        result = service.probe_draft(body.to_draft(), source_id=body.source_id)
    except (
        DataSourceNotFound,
        DataSourceValidationError,
        UnsafeConnectionTarget,
        ValueError,
    ) as exc:
        raise ValidationFailed(str(exc)) from exc
    snapshot = result.schema_snapshot
    columns = {}
    if snapshot is not None:
        columns = {name: list(cols) for name, cols in snapshot.columns.items()}
    return {
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "database": result.database,
        "server_version": result.server_version,
        "tables": list(snapshot.objects) if snapshot else [],
        "columns": columns,
        "errors": list(result.errors),
    }


@router.put("/tools/query_db/config", status_code=status.HTTP_200_OK)
def save_query_tool_config(
    body: QueryToolConfigRequest,
    service: DataSourceServiceDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    selected = tuple(item.strip() for item in body.allowed_objects if item.strip())
    if not selected:
        raise ValidationFailed("请至少勾选一张表")
    draft = body.to_draft()
    from dataclasses import replace

    draft = replace(draft, allowed_objects=selected)
    try:
        record = _upsert_query_source(service, draft, body.source_id, principal.user_id)
        service.activate(record.id, principal.user_id)
        record = service.get(record.id)
    except (
        DataSourceNotFound,
        DataSourceValidationError,
        UnsafeConnectionTarget,
        ValueError,
    ) as exc:
        raise ValidationFailed(str(exc)) from exc
    return {
        "source": {
            "id": record.id,
            "name": record.name,
            "state": record.state.value,
            "credential_configured": bool(record.secret_ref),
        },
        "selected": list(record.allowed_objects),
    }


def _bound_query_source(service: DataSourceService):
    records = service.list()
    named = [item for item in records if item.name == QUERY_TOOL_NAME]
    if named:
        return named[0]
    active = [item for item in records if item.state is DataSourceState.ACTIVE]
    if active:
        return active[0]
    return records[0] if records else None


def _empty_query_form() -> dict[str, object]:
    return {
        "source_id": "",
        "name": QUERY_TOOL_NAME,
        "connection_url": "",
        "username": "",
        "selected_database": "",
        "schema": "",
        "dialect": "mysql",
        "ssl_mode": "disable",
        "query_timeout_seconds": 15,
        "max_rows": 2000,
        "allow_private_network": True,
    }


def _snapshot_tables(repository, record) -> tuple[list[str], dict[str, list[str]]]:
    if record.current_revision <= 0:
        return [], {}
    for revision in repository.list_revisions(record.id):
        if revision.revision != record.current_revision or not revision.schema_snapshot_id:
            continue
        snapshot = repository.get_schema_snapshot(revision.schema_snapshot_id)
        if snapshot is None:
            return list(record.allowed_objects), {}
        return list(snapshot.objects), {name: list(cols) for name, cols in snapshot.columns.items()}
    return list(record.allowed_objects), {}


def _upsert_query_source(service: DataSourceService, draft, source_id: str | None, actor_id: str):
    if source_id:
        try:
            return service.update(source_id, draft, actor_id)
        except DataSourceNotFound as exc:
            raise NotFound("data source not found") from exc
    bound = _bound_query_source(service)
    if bound is not None:
        return service.update(bound.id, draft, actor_id)
    return service.create(draft, actor_id)
