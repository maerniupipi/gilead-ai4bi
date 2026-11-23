"""Administrator-only registry of selectable chat models.

The active configuration is what the agent loop runs against. API keys are
accepted on write, stored encrypted behind an opaque ref, and never returned.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from xiaoying_quick.api.dependencies import DbSession, SecretStoreDep, require_roles
from xiaoying_quick.infrastructure.llm.registry import ModelRegistry
from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
    SqlAlchemyModelConfigRepository,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.models import ModelConfigService
from xiaoying_quick.shared.ids import new_id

router = APIRouter(prefix="/api/v2/admin/model-configs", tags=["model-admin"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ModelConfigCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=160)
    endpoint_url: str = Field(min_length=1, max_length=2048)
    model_id: str = Field(min_length=1, max_length=160)
    api_key: SecretStr
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=16_384, ge=2_048, le=65_536)
    reasoning: Literal["auto", "on", "off"] = "auto"
    timeout_seconds: float = Field(default=180.0, gt=0, le=300.0)
    activate: bool = False


class ModelConfigUpdateRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model_id: str | None = Field(default=None, min_length=1, max_length=160)
    api_key: SecretStr | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=2_048, le=65_536)
    reasoning: Literal["auto", "on", "off"] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300.0)


def get_model_service(session: DbSession, secrets: SecretStoreDep) -> ModelConfigService:
    return ModelConfigService(
        SqlAlchemyModelConfigRepository(session),
        secrets,
        id_factory=lambda: new_id("model"),
    )


ModelServiceDep = Annotated[ModelConfigService, Depends(get_model_service)]


def _build_registry(session: DbSession, secrets: SecretStoreDep) -> ModelRegistry:
    return ModelRegistry(get_model_service(session, secrets), secrets)


@router.get("", status_code=status.HTTP_200_OK)
def list_configs(
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    registry = _build_registry(session, secrets)
    records = registry.service().list_configs()
    return {
        "items": [record.to_public_record() for record in records],
        "active_id": next((r.id for r in records if r.is_active), None),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_config(
    body: ModelConfigCreateRequest,
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    service = get_model_service(session, secrets)
    record = service.create(
        name=body.name,
        endpoint_url=body.endpoint_url,
        model_id=body.model_id,
        api_key=body.api_key.get_secret_value(),
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        reasoning=body.reasoning,
        timeout_seconds=body.timeout_seconds,
        activate=body.activate,
    )
    return record.to_public_record()


@router.patch("/{config_id}", status_code=status.HTTP_200_OK)
def update_config(
    config_id: str,
    body: ModelConfigUpdateRequest,
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    service = get_model_service(session, secrets)
    record = service.update(
        config_id,
        name=body.name,
        endpoint_url=body.endpoint_url,
        model_id=body.model_id,
        api_key=body.api_key.get_secret_value() if body.api_key is not None else None,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        reasoning=body.reasoning,
        timeout_seconds=body.timeout_seconds,
    )
    return record.to_public_record()


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    config_id: str,
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> None:
    del principal
    get_model_service(session, secrets).delete(config_id)


@router.post("/{config_id}/activate", status_code=status.HTTP_200_OK)
def activate_config(
    config_id: str,
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    record = get_model_service(session, secrets).activate(config_id)
    return record.to_public_record()


@router.post("/{config_id}/test", status_code=status.HTTP_200_OK)
async def test_config(
    config_id: str,
    session: DbSession,
    secrets: SecretStoreDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    registry = _build_registry(session, secrets)
    record = registry.service().get(config_id)
    return await registry.test(record)
