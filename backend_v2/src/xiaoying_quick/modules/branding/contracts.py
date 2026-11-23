"""Workspace branding: one visible identity per deployment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from xiaoying_quick.shared.compat import StrEnum

WORKSPACE_ID = "workspace"
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_CHARACTER_NAME = 32
MAX_COMPANY_INTRO = 64


class LogoKind(StrEnum):
    PRESET = "preset"
    UPLOAD = "upload"


@dataclass(frozen=True)
class LogoPreset:
    id: str
    name: str
    description: str
    url: str

    def to_public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
        }


@dataclass(frozen=True)
class ThemePreset:
    id: str
    name: str
    description: str
    tokens: dict[str, str]

    def to_public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tokens": dict(self.tokens),
        }


@dataclass(frozen=True)
class BrandingRecord:
    character_name: str
    company_intro: str
    theme_id: str
    logo_kind: LogoKind
    logo_preset_id: str
    logo_asset_id: str | None
    updated_at: datetime | None
    updated_by: str | None
