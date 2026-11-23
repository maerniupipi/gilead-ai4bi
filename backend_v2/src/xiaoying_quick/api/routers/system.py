"""Unauthenticated operational endpoints with non-secret responses."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from xiaoying_quick import __version__
from xiaoying_quick.api.dependencies import (
    get_data_source_service,
    get_identity_service,
    get_secret_store,
)
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.bootstrap_runtime import (
    bootstrap_uat_runtime,
)
from xiaoying_quick.infrastructure.persistence.provision import (
    inspect_application_database,
    provision_application_database,
)
from xiaoying_quick.infrastructure.persistence.sql_script import apply_sql_script
from xiaoying_quick.modules.health import ReadinessService
from xiaoying_quick.shared.errors import AuthenticationFailed, Forbidden, ValidationFailed

router = APIRouter(prefix="/api/v2/health", tags=["system"])
provision_router = APIRouter(prefix="/api/v2/system", tags=["system"])


@router.get("")
@router.get("/live")
def liveness() -> dict[str, str]:
    """Process-only signal; it deliberately does not touch dependencies."""

    return {"status": "ok", "service": "xiaoying-quick", "version": __version__}


@router.get("/ready")
def readiness(request: Request) -> JSONResponse:
    service = cast(ReadinessService, request.app.state.readiness_service)
    report = service.report()
    response_status = status.HTTP_200_OK if report.ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=response_status, content=report.to_record())


def _authorize_provision(settings: Settings, request: Request) -> None:
    configured = settings.provision_token
    provided = request.headers.get("X-Provision-Token")
    if configured is not None:
        if provided != configured.get_secret_value():
            raise AuthenticationFailed("provision token is invalid")
        return
    if settings.environment == "production":
        raise Forbidden("provision token is required in production")


@provision_router.get("/database")
def database_status(request: Request) -> dict[str, object]:
    settings = cast(Settings, request.app.state.settings)
    _authorize_provision(settings, request)
    return inspect_application_database(settings.database_url).to_record()


@provision_router.post("/provision")
def provision_database(request: Request) -> dict[str, object]:
    settings = cast(Settings, request.app.state.settings)
    _authorize_provision(settings, request)
    try:
        return provision_application_database(settings.database_url).to_record()
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


class BootstrapAdminRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=128)


@provision_router.post("/bootstrap-admin")
def bootstrap_admin(request: Request, body: BootstrapAdminRequest) -> dict[str, object]:
    settings = cast(Settings, request.app.state.settings)
    _authorize_provision(settings, request)
    session = request.app.state.session_factory()
    try:
        service = get_identity_service(request, session)
        user = service.bootstrap_first_admin(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
        )
        session.commit()
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.value,
            "created": True,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_MAX_IMPORT_BYTES = 8 * 1024 * 1024


class ImportSqlJson(BaseModel):
    sql: str = Field(min_length=1, max_length=_MAX_IMPORT_BYTES)


@provision_router.post("/import-sql")
async def import_sql(request: Request) -> dict[str, object]:
    """Load an AgentLoop dump (02_AgentLoop.sql) into the configured database."""

    settings = cast(Settings, request.app.state.settings)
    _authorize_provision(settings, request)
    script = await _read_import_sql(request)
    try:
        report = apply_sql_script(request.app.state.engine, script)
    except RuntimeError as exc:
        raise ValidationFailed(str(exc)) from exc
    return {"imported": True, **report}


async def _read_import_sql(request: Request) -> str:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        read = getattr(upload, "read", None)
        if not callable(read):
            raise ValidationFailed("请用 form 字段 file 上传 SQL 文件")
        payload = await read()
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
    elif "application/json" in content_type:
        body = ImportSqlJson.model_validate(await request.json())
        return body.sql
    else:
        payload = await request.body()
    if not isinstance(payload, (bytes, bytearray)):
        raise ValidationFailed("SQL 内容无法读取")
    if len(payload) > _MAX_IMPORT_BYTES:
        raise ValidationFailed("SQL 文件超过 8MB 上限")
    if not payload.strip():
        raise ValidationFailed("没有收到 SQL 内容")
    try:
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("SQL 文件必须是 UTF-8") from exc


@provision_router.post("/bootstrap-runtime")
def bootstrap_runtime(request: Request) -> dict[str, object]:
    settings = cast(Settings, request.app.state.settings)
    _authorize_provision(settings, request)
    session = request.app.state.session_factory()
    try:
        identity = get_identity_service(request, session)
        data_sources = get_data_source_service(
            request,
            session,
            get_secret_store(request),
        )
        report = bootstrap_uat_runtime(
            identity=identity,
            data_sources=data_sources,
            lab_http_configured=settings.lab_endpoint_url is not None,
        )
        session.commit()
        return report.to_record()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
