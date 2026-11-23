"""Skill pack admin CRUD and chat-facing mountable list."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from xiaoying_quick.api.dependencies import (
    CurrentPrincipal,
    DbSession,
    RunServiceDep,
    require_roles,
)
from xiaoying_quick.application.skill_drafts import draft_answer_skill
from xiaoying_quick.bootstrap.container import build_model_registry
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.repositories.skill_packs import (
    SqlAlchemySkillPackRepository,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.runs.contracts import RunStatus
from xiaoying_quick.modules.skill_packs import (
    SkillPackService,
    SkillPackStatus,
    SkillPackType,
)
from xiaoying_quick.modules.usage import UsageAttribution, bind_usage_attribution
from xiaoying_quick.shared.errors import Conflict

admin_router = APIRouter(prefix="/api/v2/admin/skill-packs", tags=["skill-packs-admin"])
public_router = APIRouter(prefix="/api/v2/skill-packs", tags=["skill-packs"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillPackCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=160)
    type: Literal["data_insight"] = "data_insight"
    prompt: str = Field(min_length=1, max_length=50_000)
    blurb: str = Field(default="", max_length=2000)


class SkillPackUpdateRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    prompt: str | None = Field(default=None, min_length=1, max_length=50_000)
    blurb: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "disabled"] | None = None


def get_skill_pack_service(session: DbSession) -> SkillPackService:
    return SkillPackService(SqlAlchemySkillPackRepository(session))


SkillPackServiceDep = Annotated[SkillPackService, Depends(get_skill_pack_service)]


@admin_router.post("/from-run/{run_id}/draft", status_code=status.HTTP_200_OK)
async def draft_from_answer(
    run_id: str,
    request: Request,
    principal: AdminPrincipal,
    database: DbSession,
    runs: RunServiceDep,
) -> dict[str, object]:
    """Generate a reviewable draft; saving uses the existing skill pack CRUD."""
    run = runs.get_run(principal=principal, run_id=run_id)
    if run.status != RunStatus.COMPLETED:
        raise Conflict("请等待回答完成后再沉淀技能。")
    events = SqlAlchemyRunRepository(database).list_events(run_id=run_id, after=0, limit=1000)
    answer = next(
        (
            str(e.payload.get("answer") or "")
            for e in reversed(events.items)
            if e.event_type == "agent.done"
        ),
        "",
    )
    if not answer.strip():
        raise Conflict("当前回答没有可沉淀的正文。")
    method = []
    for event in events.items:
        if event.event_type != "tool.call":
            continue
        name = event.payload.get("name")
        args = event.payload.get("arguments") or {}
        if name in {"ask_lab", "update_ledger", "knowledge_read"}:
            method.append(
                {
                    "tool": name,
                    "arguments": {
                        key: str(args[key])[:1500]
                        for key in ("question", "remark", "key", "kind", "text", "path")
                        if key in args
                    },
                }
            )
    report = SqlAlchemyArtifactRepository(database).latest(run_id=run_id, kind="bi_report")
    client = build_model_registry(database, request.app).active_client()
    if client is None:
        raise Conflict("请先配置可用模型，再生成技能草稿。")
    try:
        with bind_usage_attribution(
            UsageAttribution(
                user_id=principal.user_id,
                username=principal.username,
                display_name=principal.display_name,
                run_id=run.id,
                session_id=run.session_id,
                mode=run.mode.value,
                question=run.question,
            )
        ):
            draft = await draft_answer_skill(
                client,
                question=run.question,
                answer=answer,
                method=method,
                report=report,
            )
    finally:
        await client.aclose()
    return {"draft": draft.model_dump(), "source_run_id": run.id}


@admin_router.get("", status_code=status.HTTP_200_OK)
def admin_list_packs(
    service: SkillPackServiceDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    return {"items": [item.to_public_record() for item in service.list_packs()]}


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def admin_create_pack(
    body: SkillPackCreateRequest,
    service: SkillPackServiceDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    record = service.create(
        name=body.name,
        pack_type=SkillPackType.DATA_INSIGHT,
        prompt=body.prompt,
        blurb=body.blurb,
        created_by=principal.user_id,
    )
    return {"item": record.to_public_record()}


@admin_router.patch("/{pack_id}", status_code=status.HTTP_200_OK)
def admin_update_pack(
    pack_id: str,
    body: SkillPackUpdateRequest,
    service: SkillPackServiceDep,
    principal: AdminPrincipal,
) -> dict[str, object]:
    del principal
    status_value = SkillPackStatus(body.status) if body.status else None
    record = service.update(
        pack_id,
        name=body.name,
        prompt=body.prompt,
        blurb=body.blurb,
        status=status_value,
    )
    return {"item": record.to_public_record()}


@admin_router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_pack(
    pack_id: str,
    service: SkillPackServiceDep,
    principal: AdminPrincipal,
) -> None:
    del principal
    service.delete(pack_id)


@public_router.get("/mountable", status_code=status.HTTP_200_OK)
def list_mountable_insight_packs(
    service: SkillPackServiceDep,
    principal: CurrentPrincipal,
) -> dict[str, object]:
    """Chat-facing list: active data_insight packs only."""

    del principal
    return {"items": [item.to_public_record() for item in service.list_mountable_insight()]}
