"""Administrator-only audit event query API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from xiaoying_quick.api.dependencies import DbSession, require_roles
from xiaoying_quick.infrastructure.persistence.models.data_sources import AuditEventModel
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role

router = APIRouter(prefix="/api/v2/admin/audit-events", tags=["audit-admin"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secret_ref",
        "token",
        "access_token",
        "api_key",
        "master_key",
        "credential",
    }
)
_CREDENTIAL_URL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@")
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|access[_-]?token|api[_-]?key)\s*[:=]\s*\S+"
)


class AuditEventResponse(BaseModel):
    id: str
    actor_id: str
    action: str
    resource_id: str
    metadata: dict[str, Any]
    created_at: datetime


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    normalized_key = key.casefold().replace("-", "_") if key else ""
    if normalized_key and (
        normalized_key in _SENSITIVE_KEYS
        or any(marker in normalized_key for marker in _SENSITIVE_KEYS)
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item, key=str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        value = _CREDENTIAL_URL.sub(r"\1[REDACTED]@", value)
        return _INLINE_SECRET.sub(r"\1=[REDACTED]", value)
    return value


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    session: DbSession,
    _admin: AdminPrincipal,
    actor_id: Annotated[str | None, Query(max_length=64)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_id: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventResponse]:
    statement = select(AuditEventModel)
    if actor_id:
        statement = statement.where(AuditEventModel.actor_id == actor_id)
    if action:
        statement = statement.where(AuditEventModel.action == action)
    if resource_id:
        statement = statement.where(AuditEventModel.resource_id == resource_id)
    statement = statement.order_by(AuditEventModel.created_at.desc()).limit(limit).offset(offset)
    rows = session.scalars(statement).all()
    return [
        AuditEventResponse(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            resource_id=row.resource_id,
            metadata=_sanitize(row.event_metadata),
            created_at=row.created_at,
        )
        for row in rows
    ]
