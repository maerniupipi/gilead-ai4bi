"""Skill pack service rules."""

from __future__ import annotations

from datetime import datetime, timezone

from xiaoying_quick.modules.skill_packs.contracts import (
    SkillPackRecord,
    SkillPackStatus,
    SkillPackType,
)
from xiaoying_quick.modules.skill_packs.service import SkillPackService
from xiaoying_quick.shared.errors import Conflict, ValidationFailed


class _MemoryRepo:
    def __init__(self) -> None:
        self._items: dict[str, SkillPackRecord] = {}

    def get(self, pack_id: str) -> SkillPackRecord | None:
        return self._items.get(pack_id)

    def list_all(self) -> tuple[SkillPackRecord, ...]:
        return tuple(self._items.values())

    def list_by_type(
        self, pack_type: SkillPackType, *, active_only: bool = False
    ) -> tuple[SkillPackRecord, ...]:
        items = [item for item in self._items.values() if item.type is pack_type]
        if active_only:
            items = [item for item in items if item.status is SkillPackStatus.ACTIVE]
        return tuple(items)

    def add(self, record: SkillPackRecord) -> SkillPackRecord:
        self._items[record.id] = record
        return record

    def save(self, record: SkillPackRecord) -> SkillPackRecord:
        self._items[record.id] = record
        return record

    def delete(self, pack_id: str) -> None:
        self._items.pop(pack_id, None)


def test_ensure_seeded_adds_sql_generate() -> None:
    service = SkillPackService(_MemoryRepo())
    service.ensure_seeded()
    packs = service.list_packs()
    assert any(
        item.id == "sql_generate" and item.type is SkillPackType.SQL_GENERATE for item in packs
    )


def test_create_only_data_insight() -> None:
    service = SkillPackService(_MemoryRepo())
    created = service.create(
        name="区域洞察",
        pack_type=SkillPackType.DATA_INSIGHT,
        prompt="关注达成与风险",
        blurb="测试",
    )
    assert created.type is SkillPackType.DATA_INSIGHT
    try:
        service.create(
            name="bad",
            pack_type=SkillPackType.SQL_GENERATE,
            prompt="x",
        )
        raise AssertionError("expected ValidationFailed")
    except ValidationFailed:
        pass


def test_sql_seed_not_deletable_and_prompt_locked() -> None:
    service = SkillPackService(_MemoryRepo())
    service.ensure_seeded()
    try:
        service.delete("sql_generate")
        raise AssertionError("expected Conflict")
    except Conflict:
        pass
    try:
        service.update("sql_generate", prompt="hacked")
        raise AssertionError("expected ValidationFailed")
    except ValidationFailed:
        pass


def test_mountable_filters_active_insight_only() -> None:
    repo = _MemoryRepo()
    now = datetime.now(timezone.utc)
    repo.add(
        SkillPackRecord(
            id="i1",
            name="A",
            type=SkillPackType.DATA_INSIGHT,
            prompt="p",
            blurb="",
            status=SkillPackStatus.ACTIVE,
            created_by=None,
            created_at=now,
            updated_at=now,
        )
    )
    repo.add(
        SkillPackRecord(
            id="i2",
            name="B",
            type=SkillPackType.DATA_INSIGHT,
            prompt="p",
            blurb="",
            status=SkillPackStatus.DISABLED,
            created_by=None,
            created_at=now,
            updated_at=now,
        )
    )
    service = SkillPackService(repo)
    service.ensure_seeded()
    mountable = service.list_mountable_insight()
    assert [item.id for item in mountable] == [
        "i1",
        "ddi_analysis",
        "html_template",
        "moc_overview",
        "moc_attainment",
        "moc_growth",
        "moc_structure",
    ]
