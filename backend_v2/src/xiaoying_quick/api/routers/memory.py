"""Current-user personal memory API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from xiaoying_quick.api.dependencies import (
    CurrentPrincipal,
    PersonalMemoryServiceDep,
    RunServiceDep,
)
from xiaoying_quick.modules.knowledge.content_guard import (
    KnowledgeContentGuard,
    UnsafeKnowledgeContent,
)
from xiaoying_quick.modules.knowledge.contracts import (
    KnowledgeState,
    MemoryUpdateRequest,
    MemoryWriteRequest,
    PersonalMemoryEntry,
    PersonalMemoryRevision,
)
from xiaoying_quick.shared.errors import Conflict, NotFound, ValidationFailed

router = APIRouter(prefix="/api/v2/memory", tags=["personal-memory"])


class MemoryWriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(default="preference", min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    source_run_id: str | None = Field(default=None, max_length=64)


class MemoryUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(default="preference", min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    source_run_id: str | None = Field(default=None, max_length=64)


class MemoryResponse(BaseModel):
    id: str
    owner_id: str
    category: str
    content: str
    source_run_id: str | None
    state: KnowledgeState
    created_at: datetime
    revoked_at: datetime | None
    version: int


class MemoryRevisionResponse(BaseModel):
    id: str
    memory_id: str
    version: int
    category: str
    content: str
    source_run_id: str | None
    state: KnowledgeState
    created_at: datetime


T = TypeVar("T")


def _translate(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except LookupError as exc:
        raise NotFound("personal memory entry not found") from exc
    except IntegrityError as exc:
        raise Conflict("personal memory references an unavailable resource") from exc
    except (UnsafeKnowledgeContent, ValueError) as exc:
        raise ValidationFailed(str(exc)) from exc


def _response(value: PersonalMemoryEntry) -> MemoryResponse:
    return MemoryResponse(
        id=value.id,
        owner_id=value.owner_id,
        category=value.category,
        content=value.content,
        source_run_id=value.source_run_id,
        state=value.state,
        created_at=value.created_at,
        revoked_at=value.revoked_at,
        version=value.version,
    )


def _revision_response(value: PersonalMemoryRevision) -> MemoryRevisionResponse:
    return MemoryRevisionResponse(
        id=value.id,
        memory_id=value.memory_id,
        version=value.version,
        category=value.category,
        content=value.content,
        source_run_id=value.source_run_id,
        state=value.state,
        created_at=value.created_at,
    )


@router.get("", response_model=list[MemoryResponse])
def list_memory(
    principal: CurrentPrincipal, service: PersonalMemoryServiceDep
) -> list[MemoryResponse]:
    return [_response(entry) for entry in _translate(lambda: service.list(principal.user_id))]


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def write_memory(
    body: MemoryWriteBody,
    principal: CurrentPrincipal,
    service: PersonalMemoryServiceDep,
    run_service: RunServiceDep,
) -> MemoryResponse:
    if body.source_run_id:
        run_service.get_run(principal=principal, run_id=body.source_run_id)
    safe_category = _translate(lambda: KnowledgeContentGuard().validate(body.category))
    entry = _translate(
        lambda: service.write(
            principal.user_id,
            MemoryWriteRequest(
                category=safe_category,
                content=body.content,
                source_run_id=body.source_run_id,
            ),
        )
    )
    return _response(entry)


@router.put("/{entry_id}", response_model=MemoryResponse)
def update_memory(
    entry_id: str,
    body: MemoryUpdateBody,
    principal: CurrentPrincipal,
    service: PersonalMemoryServiceDep,
    run_service: RunServiceDep,
) -> MemoryResponse:
    if body.source_run_id:
        run_service.get_run(principal=principal, run_id=body.source_run_id)
    safe_category = _translate(lambda: KnowledgeContentGuard().validate(body.category))
    entry = _translate(
        lambda: service.update(
            principal.user_id,
            entry_id,
            MemoryUpdateRequest(
                category=safe_category,
                content=body.content,
                source_run_id=body.source_run_id,
            ),
        )
    )
    return _response(entry)


@router.get("/{entry_id}/history", response_model=list[MemoryRevisionResponse])
def memory_history(
    entry_id: str,
    principal: CurrentPrincipal,
    service: PersonalMemoryServiceDep,
) -> list[MemoryRevisionResponse]:
    return [
        _revision_response(revision)
        for revision in _translate(lambda: service.history(principal.user_id, entry_id))
    ]


@router.delete("/{entry_id}", response_model=MemoryResponse)
def revoke_memory(
    entry_id: str,
    principal: CurrentPrincipal,
    service: PersonalMemoryServiceDep,
) -> MemoryResponse:
    return _response(_translate(lambda: service.revoke(principal.user_id, entry_id)))
