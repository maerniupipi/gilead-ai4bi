"""Administrator laboratory provider configuration and unsaved draft testing."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from xiaoying_quick.api.dependencies import (
    DbSession,
    SecretStoreDep,
    get_settings,
    require_roles,
)
from xiaoying_quick.application.lab_connection import LabConnectionService
from xiaoying_quick.infrastructure.lab_http.adapter import HttpLabAdapter
from xiaoying_quick.infrastructure.lab_http.bootcamp import BootcampLabAdapter, BootcampLabConfig
from xiaoying_quick.infrastructure.lab_http.config import LabHttpConfig
from xiaoying_quick.infrastructure.lab_http.errors import LabHttpError
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.labs import LabRequest
from xiaoying_quick.modules.labs.ports import LabPort
from xiaoying_quick.shared.errors import ValidationFailed

router = APIRouter(prefix="/api/v2/admin/lab-connection", tags=["lab-connection"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]
Provider = Literal["bailian", "bootcamp"]
LabId = Literal["actual", "demand", "ext_simple", "ext_complex"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LabMappingRequest(StrictRequest):
    lab_id: LabId
    token: str | None = Field(default=None, max_length=4096, repr=False)
    api_access_id: str | None = Field(default=None, max_length=128)


class LabProfileRequest(StrictRequest):
    provider: Provider
    endpoint_url: str = Field(max_length=2048)
    timeout_seconds: float = Field(default=120, ge=1, le=600)
    authorization: str | None = Field(default=None, max_length=4096, repr=False)
    user_id: int = Field(default=1, ge=1)
    space_id: int = Field(default=1, ge=1)
    labs: list[LabMappingRequest] = Field(default_factory=list, max_length=4)


class LabConnectionUpdate(StrictRequest):
    active_provider: Provider
    mock_enabled: bool = False
    profile: LabProfileRequest


class LabConnectionTest(LabConnectionUpdate):
    lab_id: LabId = "actual"
    query: str = Field(default="查询销售数据", min_length=1, max_length=4000)


def get_lab_connection_service(
    request: Request, session: DbSession, secrets: SecretStoreDep
) -> LabConnectionService:
    return LabConnectionService(session, get_settings(request), secrets)


ServiceDep = Annotated[LabConnectionService, Depends(get_lab_connection_service)]


class LabPair(StrictRequest):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    name: str = Field(min_length=1, max_length=96)
    recall: str = Field(pattern=r"^[a-zA-Z0-9]{10}$")
    sql: str = Field(pattern=r"^[a-zA-Z0-9]{10}$")


class PairsUpdate(StrictRequest):
    endpoint_url: str = Field(max_length=2048)
    authorization: str | None = Field(default=None, max_length=4096, repr=False)
    pairs: list[LabPair] = Field(min_length=1, max_length=32)


@router.get("/pairs")
def get_pairs(service: ServiceDep, admin: AdminPrincipal):
    return service.pairs()


@router.put("/pairs")
def save_pairs(body: PairsUpdate, service: ServiceDep, admin: AdminPrincipal, request: Request):
    current = {pair["id"] for pair in service.pairs()["pairs"]}
    removed = current - {pair.id for pair in body.pairs}
    if removed:
        from .chatbots import get_chatbot_store
        for chatbot in get_chatbot_store(request).list():
            if removed.intersection(chatbot["lab_ids"]):
                raise ValidationFailed("请先在 Chatbot 管理中更新“"+chatbot["name"]+"”绑定的实验室组合")
    return service.save_pairs(body.model_dump(), admin.user_id)


@router.get("")
def get_connection(service: ServiceDep, admin: AdminPrincipal) -> dict[str, object]:
    return service.public_payload()


@router.put("")
def save_connection(
    body: LabConnectionUpdate, service: ServiceDep, admin: AdminPrincipal
) -> dict[str, object]:
    if service.pairs()["pairs"]:
        raise ValidationFailed("请使用吉利德AI平台的成对实验室配置")
    return service.save(body.model_dump(exclude_none=True), actor_id=admin.user_id)


@router.post("/test")
async def test_connection(
    body: LabConnectionTest, request: Request, service: ServiceDep, admin: AdminPrincipal
) -> dict[str, object]:
    del admin
    adapter: LabPort | None = None
    result: dict[str, object] = {
        "ok": False,
        "message": "",
        "provider": body.profile.provider,
        "lab_id": body.lab_id,
        "candidate_count": 0,
        "mock_enabled": body.mock_enabled,
    }
    try:
        resolved = service.preview(body.model_dump(exclude_none=True))
        settings = get_settings(request)
        if resolved.mock_enabled:
            from xiaoying_quick.infrastructure.lab_http.demo import DemoLabPort

            adapter = DemoLabPort(provider=resolved.provider)
        elif resolved.provider == "bootcamp":
            adapter = BootcampLabAdapter(
                BootcampLabConfig(
                    endpoint_url=resolved.endpoint_url,
                    authorization=resolved.authorization,
                    lab_ids=resolved.lab_credentials,
                    timeout_seconds=resolved.timeout_seconds,
                    user_id=resolved.user_id,
                    space_id=resolved.space_id,
                    allow_insecure_http=settings.environment != "production",
                    max_response_bytes=settings.lab_max_response_bytes,
                )
            )
        else:
            adapter = HttpLabAdapter(
                LabHttpConfig(
                    endpoint_url=resolved.endpoint_url,
                    lab_tokens=resolved.lab_credentials,
                    timeout_seconds=resolved.timeout_seconds,
                    allow_insecure_http=settings.environment != "production",
                    max_response_bytes=settings.lab_max_response_bytes,
                )
            )
        candidates = await adapter.generate_sql(
            LabRequest(
                atom_id="connection-test",
                lab_id=body.lab_id,
                query=body.query,
            )
        )
        if resolved.mock_enabled:
            from xiaoying_quick.infrastructure.lab_http.demo import get_demo_gateway

            gateway = get_demo_gateway(settings.secret_store_path.parent / "demo-labs-v1.sqlite")
            for candidate in candidates:
                gateway.execute(candidate.sql, 30)
        result.update(
            ok=True,
            candidate_count=len(candidates),
            message=(
                "演示数据已就绪（未访问外部平台）"
                if resolved.mock_enabled
                else "连接成功，实验室已返回 SQL"
            ),
        )
    except ValidationFailed as exc:
        result["message"] = exc.message
    except ValueError as exc:
        # Only configuration constructors above may raise a ValueError here;
        # messages never include credentials or remote response contents.
        result["message"] = str(exc)
    except LabHttpError as exc:
        messages = {
            "timeout": "请求超时，请检查服务状态或增加超时时间",
            "network_error": "无法连接实验室，请检查服务地址和网络",
            "http_client_error": "请求被拒绝，请检查内部密钥、空间及实验室调用 ID",
            "invalid_response": "实验室未返回有效的 SQL，请检查该实验室配置",
            "invalid_request": "该实验室尚未配置有效的访问凭据或 API 调用 ID",
        }
        result["message"] = messages.get(exc.code.value, "实验室请求失败，请检查平台服务状态")
    except Exception:
        result["message"] = "实验室测试失败，请检查配置后重试"
    finally:
        if adapter is not None and hasattr(adapter, "aclose"):
            await adapter.aclose()
    return result
