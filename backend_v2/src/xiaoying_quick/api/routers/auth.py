"""Credential exchange, current identity, and administrator user creation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator

from xiaoying_quick.api.dependencies import (
    CurrentPrincipal,
    IdentityServiceDep,
    require_roles,
)
from xiaoying_quick.modules.identity.contracts import (
    AuthenticatedPrincipal,
    DataAccessScope,
    DataScopeMode,
    Role,
    UserRecord,
)

router = APIRouter(prefix="/api/v2/auth", tags=["identity"])


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime | None = None
    user: UserResponse


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=128)
    role: Role = Role.USER
    data_scope: DataScopeRequest | None = None


class DataScopeRequest(BaseModel):
    mode: DataScopeMode
    organizations: list[str] = Field(default_factory=list, max_length=128)
    regions: list[str] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self) -> DataScopeRequest:
        self.to_scope()
        return self

    def to_scope(self) -> DataAccessScope:
        return DataAccessScope(
            mode=self.mode,
            organizations=tuple(self.organizations),
            regions=tuple(self.regions),
        )


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime


class DataScopeResponse(BaseModel):
    user_id: str
    mode: DataScopeMode
    organizations: list[str]
    regions: list[str]
    version: int


def _user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _principal_response(principal: AuthenticatedPrincipal) -> dict[str, str]:
    return {
        "id": principal.user_id,
        "username": principal.username,
        "display_name": principal.display_name,
        "role": principal.role.value,
    }


@router.post("/token", response_model=TokenResponse)
def issue_token(body: TokenRequest, service: IdentityServiceDep) -> TokenResponse:
    token, user, expires_at = service.authenticate(username=body.username, password=body.password)
    return TokenResponse(access_token=token, expires_at=expires_at, user=_user_response(user))


@router.get("/me")
def current_identity(principal: CurrentPrincipal) -> dict[str, str]:
    return _principal_response(principal)


AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


class UserListItem(UserResponse):
    data_scope: DataScopeResponse


@router.get("/users")
def list_users(service: IdentityServiceDep, admin: AdminPrincipal) -> dict[str, object]:
    items = []
    for user in service.list_users(actor=admin):
        items.append(
            UserListItem(
                **_user_response(user).model_dump(),
                data_scope=_scope_response(user.id, user.data_scope),
            ).model_dump(mode="json")
        )
    return {"items": items}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateRequest,
    service: IdentityServiceDep,
    _admin: AdminPrincipal,
) -> UserResponse:
    user = service.create_user(
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        role=body.role,
        data_scope=body.data_scope.to_scope() if body.data_scope else None,
    )
    return _user_response(user)


@router.get("/users/{user_id}/data-scope", response_model=DataScopeResponse)
def get_user_data_scope(
    user_id: str,
    service: IdentityServiceDep,
    admin: AdminPrincipal,
) -> DataScopeResponse:
    return _scope_response(user_id, service.get_data_scope(actor=admin, user_id=user_id))


@router.put("/users/{user_id}/data-scope", response_model=DataScopeResponse)
def configure_user_data_scope(
    user_id: str,
    body: DataScopeRequest,
    service: IdentityServiceDep,
    admin: AdminPrincipal,
) -> DataScopeResponse:
    user = service.configure_data_scope(
        actor=admin,
        user_id=user_id,
        scope=body.to_scope(),
    )
    return _scope_response(user.id, user.data_scope)


def _scope_response(user_id: str, scope: DataAccessScope) -> DataScopeResponse:
    return DataScopeResponse(
        user_id=user_id,
        mode=scope.mode,
        organizations=list(scope.organizations),
        regions=list(scope.regions),
        version=scope.version,
    )
