"""SQLAlchemy repository for the singleton workspace branding row."""

from __future__ import annotations

from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.branding import WorkspaceBrandingModel
from xiaoying_quick.modules.branding.contracts import WORKSPACE_ID, BrandingRecord, LogoKind


class SqlAlchemyBrandingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> BrandingRecord | None:
        model = self._session.get(WorkspaceBrandingModel, WORKSPACE_ID)
        return _to_record(model) if model is not None else None

    def save(self, record: BrandingRecord) -> BrandingRecord:
        model = self._session.get(WorkspaceBrandingModel, WORKSPACE_ID)
        if model is None:
            model = WorkspaceBrandingModel(id=WORKSPACE_ID)
            self._session.add(model)
        model.character_name = record.character_name
        model.company_intro = record.company_intro
        model.theme_id = record.theme_id
        model.logo_kind = record.logo_kind.value
        model.logo_preset_id = record.logo_preset_id
        model.logo_asset_id = record.logo_asset_id
        model.updated_by = record.updated_by
        if record.updated_at is not None:
            model.updated_at = record.updated_at
        self._session.flush()
        return _to_record(model)


def _to_record(model: WorkspaceBrandingModel) -> BrandingRecord:
    return BrandingRecord(
        character_name=model.character_name,
        company_intro=model.company_intro,
        theme_id=model.theme_id,
        logo_kind=LogoKind(model.logo_kind),
        logo_preset_id=model.logo_preset_id,
        logo_asset_id=model.logo_asset_id,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
    )
