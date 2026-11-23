"""Public workspace branding and administrator updates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from xiaoying_quick.api.dependencies import DbSession, get_settings, require_roles
from xiaoying_quick.infrastructure.branding import LocalLogoStore
from xiaoying_quick.infrastructure.persistence.repositories.branding import (
    SqlAlchemyBrandingRepository,
)
from xiaoying_quick.modules.branding.contracts import LogoKind
from xiaoying_quick.modules.branding.service import BrandingService
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.shared.errors import ValidationFailed

public_router = APIRouter(prefix="/api/v2/branding", tags=["branding"])
admin_router = APIRouter(prefix="/api/v2/admin/branding", tags=["branding-admin"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BrandingUpdateRequest(StrictRequest):
    character_name: str = Field(min_length=1, max_length=32)
    company_intro: str = Field(min_length=1, max_length=64)
    theme_id: str = Field(min_length=1, max_length=32)
    logo_preset_id: str | None = Field(default=None, min_length=1, max_length=32)


def get_branding_service(request: Request, session: DbSession) -> BrandingService:
    settings = get_settings(request)
    return BrandingService(
        SqlAlchemyBrandingRepository(session),
        LocalLogoStore(settings.branding_assets_path),
    )


BrandingServiceDep = Annotated[BrandingService, Depends(get_branding_service)]


@public_router.get("")
def get_branding(service: BrandingServiceDep) -> dict[str, object]:
    return service.public_payload()


@public_router.get("/logo")
def get_branding_logo(service: BrandingServiceDep) -> Response:
    record = service.get()
    if record.logo_kind is LogoKind.PRESET or not record.logo_asset_id:
        target = service.logo_url(record).split("?")[0]
        return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
    content, content_type = service.load_upload(record)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@admin_router.put("")
def update_branding(
    body: BrandingUpdateRequest,
    service: BrandingServiceDep,
    admin: AdminPrincipal,
) -> dict[str, object]:
    record = service.update(
        character_name=body.character_name,
        company_intro=body.company_intro,
        theme_id=body.theme_id,
        logo_preset_id=body.logo_preset_id,
        actor_id=admin.user_id,
    )
    return service.public_payload(record)


@admin_router.post("/logo")
async def upload_branding_logo(
    service: BrandingServiceDep,
    admin: AdminPrincipal,
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    content = await file.read()
    if not content:
        raise ValidationFailed("logo file is empty")
    record = service.save_upload(content=content, actor_id=admin.user_id)
    return service.public_payload(record)
