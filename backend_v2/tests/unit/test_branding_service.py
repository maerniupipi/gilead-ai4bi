"""Branding catalog and upload sniffing."""

from __future__ import annotations

from pathlib import Path

import pytest

from xiaoying_quick.infrastructure.branding import LocalLogoStore
from xiaoying_quick.modules.branding.catalog import LOGOS, THEMES, logo_by_id, theme_by_id
from xiaoying_quick.modules.branding.contracts import BrandingRecord, LogoKind
from xiaoying_quick.modules.branding.service import BrandingService, sniff_image
from xiaoying_quick.shared.errors import ValidationFailed


class MemoryBrandingRepository:
    def __init__(self) -> None:
        self.record: BrandingRecord | None = None

    def get(self) -> BrandingRecord | None:
        return self.record

    def save(self, record: BrandingRecord) -> BrandingRecord:
        self.record = record
        return record


def test_catalog_has_formal_theme_and_three_enterprise_logos() -> None:
    assert [item.id for item in THEMES] == ["gilead", "azalea", "harbor", "pine", "amber", "slate"]
    assert logo_by_id("gilead-bi") is not None
    assert theme_by_id("harbor") is not None
    assert len(LOGOS) == 3


def test_sniff_image_rejects_unknown_and_oversized_payloads() -> None:
    assert sniff_image(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    with pytest.raises(ValidationFailed, match="png, jpeg, or webp"):
        sniff_image(b"GIF89a")
    with pytest.raises(ValidationFailed, match="2MB"):
        sniff_image(b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024))


def test_update_keeps_uploaded_logo_until_preset_is_chosen(tmp_path: Path) -> None:
    service = BrandingService(MemoryBrandingRepository(), LocalLogoStore(tmp_path))
    uploaded = service.save_upload(content=b"\x89PNG\r\n\x1a\n", actor_id="usr_admin")
    assert uploaded.logo_kind is LogoKind.UPLOAD
    kept = service.update(
        character_name="小吉",
        company_intro="吉利德业务助手",
        theme_id="pine",
        actor_id="usr_admin",
    )
    assert kept.logo_kind is LogoKind.UPLOAD
    assert kept.theme_id == "pine"
    switched = service.update(
        character_name="小吉",
        company_intro="吉利德业务助手",
        theme_id="pine",
        logo_preset_id="enterprise",
        actor_id="usr_admin",
    )
    assert switched.logo_kind is LogoKind.PRESET
    assert switched.logo_preset_id == "enterprise"
    assert service.logo_url(switched) == "/brand/enterprise.svg"
