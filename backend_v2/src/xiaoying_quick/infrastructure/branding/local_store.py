"""Filesystem store for uploaded character logos."""

from __future__ import annotations

import re
from pathlib import Path

from xiaoying_quick.shared.errors import ValidationFailed

_ASSET_ID = re.compile(r"^logo_[0-9a-f]{32}$")


class LocalLogoStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, asset_id: str, content: bytes, content_type: str) -> None:
        path = self._path(asset_id)
        path.write_bytes(content)
        path.with_suffix(".meta").write_text(content_type, encoding="utf-8")

    def load(self, asset_id: str) -> tuple[bytes, str] | None:
        path = self._path(asset_id)
        if not path.is_file():
            return None
        meta = path.with_suffix(".meta")
        content_type = meta.read_text(encoding="utf-8").strip() if meta.is_file() else "image/png"
        return path.read_bytes(), content_type or "image/png"

    def path_for(self, asset_id: str) -> Path | None:
        path = self._path(asset_id)
        return path if path.is_file() else None

    def _path(self, asset_id: str) -> Path:
        if not _ASSET_ID.fullmatch(asset_id):
            raise ValidationFailed("invalid logo asset")
        return self._root / asset_id
