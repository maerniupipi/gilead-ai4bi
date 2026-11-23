"""Skill pack contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from xiaoying_quick.shared.compat import StrEnum


class SkillPackType(StrEnum):
    SQL_GENERATE = "sql_generate"
    DATA_INSIGHT = "data_insight"


class SkillPackStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SkillPackRecord:
    id: str
    name: str
    type: SkillPackType
    prompt: str
    blurb: str
    status: SkillPackStatus
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    def to_public_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "prompt": self.prompt,
            "blurb": self.blurb,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "editable": self.type is SkillPackType.DATA_INSIGHT,
        }
