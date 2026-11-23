"""Persistence port for skill packs."""

from __future__ import annotations

from typing import Protocol

from xiaoying_quick.modules.skill_packs.contracts import SkillPackRecord, SkillPackType


class SkillPackRepository(Protocol):
    def get(self, pack_id: str) -> SkillPackRecord | None: ...

    def list_all(self) -> tuple[SkillPackRecord, ...]: ...

    def list_by_type(
        self, pack_type: SkillPackType, *, active_only: bool = False
    ) -> tuple[SkillPackRecord, ...]: ...

    def add(self, record: SkillPackRecord) -> SkillPackRecord: ...

    def save(self, record: SkillPackRecord) -> SkillPackRecord: ...

    def delete(self, pack_id: str) -> None: ...
