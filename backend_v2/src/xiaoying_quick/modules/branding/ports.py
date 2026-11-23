"""Ports owned by the branding module."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from xiaoying_quick.modules.branding.contracts import BrandingRecord


class BrandingRepository(Protocol):
    def get(self) -> BrandingRecord | None: ...

    def save(self, record: BrandingRecord) -> BrandingRecord: ...


class LogoStore(Protocol):
    def save(self, asset_id: str, content: bytes, content_type: str) -> None: ...

    def load(self, asset_id: str) -> tuple[bytes, str] | None: ...

    def path_for(self, asset_id: str) -> Path | None: ...
