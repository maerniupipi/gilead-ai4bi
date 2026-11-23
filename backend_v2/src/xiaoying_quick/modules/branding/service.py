"""Workspace branding use cases."""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from datetime import datetime, timezone

from xiaoying_quick.modules.branding.catalog import (
    DEFAULT_CHARACTER_NAME,
    DEFAULT_COMPANY_INTRO,
    DEFAULT_LOGO_ID,
    DEFAULT_THEME_ID,
    LOGOS,
    THEMES,
    logo_by_id,
    theme_by_id,
)
from xiaoying_quick.modules.branding.contracts import (
    MAX_CHARACTER_NAME,
    MAX_COMPANY_INTRO,
    MAX_LOGO_BYTES,
    BrandingRecord,
    LogoKind,
)
from xiaoying_quick.modules.branding.ports import BrandingRepository, LogoStore
from xiaoying_quick.shared.errors import NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id


def default_branding() -> BrandingRecord:
    return BrandingRecord(
        character_name=DEFAULT_CHARACTER_NAME,
        company_intro=DEFAULT_COMPANY_INTRO,
        theme_id=DEFAULT_THEME_ID,
        logo_kind=LogoKind.PRESET,
        logo_preset_id=DEFAULT_LOGO_ID,
        logo_asset_id=None,
        updated_at=None,
        updated_by=None,
    )


class BrandingService:
    def __init__(self, repository: BrandingRepository, logos: LogoStore) -> None:
        self._repository = repository
        self._logos = logos

    def get(self) -> BrandingRecord:
        record = self._repository.get() or default_branding()
        if record.logo_kind is LogoKind.PRESET and logo_by_id(record.logo_preset_id) is None:
            record = replace(
                record, character_name=DEFAULT_CHARACTER_NAME,
                company_intro=DEFAULT_COMPANY_INTRO, theme_id=DEFAULT_THEME_ID,
                logo_preset_id=DEFAULT_LOGO_ID,
            )
        return record

    def public_payload(self, record: BrandingRecord | None = None) -> dict[str, object]:
        current = record or self.get()
        theme = theme_by_id(current.theme_id) or theme_by_id(DEFAULT_THEME_ID)
        assert theme is not None
        return {
            "character_name": current.character_name,
            "company_intro": current.company_intro,
            "theme_id": theme.id,
            "logo_kind": current.logo_kind.value,
            "logo_preset_id": current.logo_preset_id,
            "logo_url": self.logo_url(current),
            "tokens": dict(theme.tokens),
            "themes": [item.to_public() for item in THEMES],
            "logos": [item.to_public() for item in LOGOS],
            "updated_at": current.updated_at.isoformat() if current.updated_at else None,
        }

    def logo_url(self, record: BrandingRecord) -> str:
        if record.logo_kind is LogoKind.UPLOAD and record.logo_asset_id:
            stamp = int(record.updated_at.timestamp()) if record.updated_at else 0
            return f"/api/v2/branding/logo?v={stamp}"
        preset = logo_by_id(record.logo_preset_id) or logo_by_id(DEFAULT_LOGO_ID)
        assert preset is not None
        return preset.url

    def update(
        self,
        *,
        character_name: str,
        company_intro: str,
        theme_id: str,
        logo_preset_id: str | None = None,
        actor_id: str,
    ) -> BrandingRecord:
        current = self.get()
        name = _clean_label(character_name, "character_name", MAX_CHARACTER_NAME)
        intro = _clean_label(company_intro, "company_intro", MAX_COMPANY_INTRO)
        if theme_by_id(theme_id) is None:
            raise ValidationFailed("unknown theme")
        logo_kind = current.logo_kind
        preset_id = current.logo_preset_id
        asset_id = current.logo_asset_id
        if logo_preset_id is not None:
            if logo_by_id(logo_preset_id) is None:
                raise ValidationFailed("unknown character logo")
            logo_kind = LogoKind.PRESET
            preset_id = logo_preset_id
            asset_id = current.logo_asset_id
        return self._repository.save(
            BrandingRecord(
                character_name=name,
                company_intro=intro,
                theme_id=theme_id,
                logo_kind=logo_kind,
                logo_preset_id=preset_id,
                logo_asset_id=asset_id,
                updated_at=_now(),
                updated_by=actor_id,
            )
        )

    def save_upload(self, *, content: bytes, actor_id: str) -> BrandingRecord:
        content_type = sniff_image(content)
        current = self.get()
        asset_id = new_id("logo")
        self._logos.save(asset_id, content, content_type)
        return self._repository.save(
            BrandingRecord(
                character_name=current.character_name,
                company_intro=current.company_intro,
                theme_id=current.theme_id,
                logo_kind=LogoKind.UPLOAD,
                logo_preset_id=current.logo_preset_id or DEFAULT_LOGO_ID,
                logo_asset_id=asset_id,
                updated_at=_now(),
                updated_by=actor_id,
            )
        )

    def load_upload(self, record: BrandingRecord) -> tuple[bytes, str]:
        if record.logo_kind is not LogoKind.UPLOAD or not record.logo_asset_id:
            raise NotFound("uploaded logo not found")
        loaded = self._logos.load(record.logo_asset_id)
        if loaded is None:
            raise NotFound("uploaded logo not found")
        return loaded


def sniff_image(content: bytes) -> str:
    if not content:
        raise ValidationFailed("logo file is empty")
    if len(content) > MAX_LOGO_BYTES:
        raise ValidationFailed("logo must be 2MB or smaller")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise ValidationFailed("logo must be png, jpeg, or webp")


def _clean_label(value: str, field: str, maximum: int) -> str:
    clean = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(clean) <= maximum:
        raise ValidationFailed(f"{field} must contain between 1 and {maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in clean):
        raise ValidationFailed(f"{field} cannot contain control characters")
    return clean


def _now() -> datetime:
    return datetime.now(timezone.utc)
