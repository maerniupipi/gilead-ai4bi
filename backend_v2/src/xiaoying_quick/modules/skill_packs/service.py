"""Skill pack use cases."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from xiaoying_quick.modules.skill_packs.contracts import (
    SkillPackRecord,
    SkillPackStatus,
    SkillPackType,
)
from xiaoying_quick.modules.skill_packs.ports import SkillPackRepository
from xiaoying_quick.shared.errors import Conflict, NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id

_SQL_SEED_ID = "sql_generate"
_SQL_SEED = SkillPackRecord(
    id=_SQL_SEED_ID,
    name="SQL生成",
    type=SkillPackType.SQL_GENERATE,
    prompt=(
        "代码技能占位：根据已召回的参考信息生成候选 SQL。本期不接入运行时，仅在技能包目录登记类型。"
    ),
    blurb="用已召回的参考信息生成候选 SQL，不查库、不召回。",
    status=SkillPackStatus.ACTIVE,
    created_by=None,
    created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
)


class SkillPackService:
    def __init__(self, repository: SkillPackRepository) -> None:
        self._repository = repository

    def ensure_seeded(self) -> None:
        if self._repository.get(_SQL_SEED_ID) is None:
            now = datetime.now(timezone.utc)
            self._repository.add(replace(_SQL_SEED, created_at=now, updated_at=now))
        for pack_id, name, blurb, folder in (
            (
                "ddi_analysis",
                "DDI分析",
                "标准DDI报表、趋势、达成、同比环比与逐层归因。",
                "ddi-analysis",
            ),
            (
                "html_template",
                "html模板",
                "正式交互报告：联动筛选、图文分析、字段编辑与HTML导出。",
                "html-template",
            ),
            (
                "moc_overview",
                "医药经营总览",
                "统一期间、金额、数量与目标口径，呈现复合图和关键数字。",
                "pharma-moc",
            ),
            (
                "moc_attainment",
                "目标达成与缺口诊断",
                "对账整体缺口，沿重点城市、产品与渠道逐层诊断。",
                "pharma-attainment",
            ),
            (
                "moc_growth",
                "增长与量价分析",
                "校验同比环比、量价关系与正负增量贡献。",
                "pharma-growth",
            ),
            (
                "moc_structure",
                "城市渠道与产品结构",
                "分析构成、集中度、费用与毛利，聚焦可验证异常。",
                "pharma-structure",
            ),
        ):
            if self._repository.get(pack_id) is not None:
                continue
            prompt = (Path(__file__).parent / "templates" / folder / "SKILL.md").read_text(
                encoding="utf-8"
            )
            now = datetime.now(timezone.utc)
            self._repository.add(
                SkillPackRecord(
                    id=pack_id,
                    name=name,
                    type=SkillPackType.DATA_INSIGHT,
                    prompt=prompt,
                    blurb=blurb,
                    status=SkillPackStatus.ACTIVE,
                    created_by=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    def list_packs(self) -> tuple[SkillPackRecord, ...]:
        self.ensure_seeded()
        return self._repository.list_all()

    def list_mountable_insight(self) -> tuple[SkillPackRecord, ...]:
        self.ensure_seeded()
        return self._repository.list_by_type(SkillPackType.DATA_INSIGHT, active_only=True)

    def get(self, pack_id: str) -> SkillPackRecord:
        self.ensure_seeded()
        record = self._repository.get(pack_id)
        if record is None:
            raise NotFound("skill pack not found")
        return record

    def create(
        self,
        *,
        name: str,
        pack_type: SkillPackType | str,
        prompt: str,
        blurb: str = "",
        created_by: str | None = None,
    ) -> SkillPackRecord:
        clean_name = _clean_name(name)
        typed = pack_type if isinstance(pack_type, SkillPackType) else SkillPackType(str(pack_type))
        if typed is not SkillPackType.DATA_INSIGHT:
            raise ValidationFailed("目前只能创建数据洞察技能包")
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValidationFailed("prompt is required")
        if len(clean_prompt) > 50_000:
            raise ValidationFailed("prompt is too long")
        now = datetime.now(timezone.utc)
        record = SkillPackRecord(
            id=new_id("skill"),
            name=clean_name,
            type=typed,
            prompt=clean_prompt,
            blurb=(blurb or "").strip()[:2000],
            status=SkillPackStatus.ACTIVE,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        return self._repository.add(record)

    def update(
        self,
        pack_id: str,
        *,
        name: str | None = None,
        prompt: str | None = None,
        blurb: str | None = None,
        status: SkillPackStatus | str | None = None,
    ) -> SkillPackRecord:
        record = self.get(pack_id)
        if record.type is SkillPackType.SQL_GENERATE:
            # SQL placeholder: allow blurb/name/status text edits only, not prompt semantics.
            if prompt is not None and prompt.strip() != record.prompt:
                raise ValidationFailed("SQL 生成技能包的提示词不可修改")
        next_name = record.name if name is None else _clean_name(name)
        next_prompt = record.prompt if prompt is None else prompt.strip()
        if prompt is not None and not next_prompt:
            raise ValidationFailed("prompt is required")
        next_blurb = record.blurb if blurb is None else blurb.strip()[:2000]
        next_status = record.status
        if status is not None:
            next_status = (
                status if isinstance(status, SkillPackStatus) else SkillPackStatus(str(status))
            )
        updated = replace(
            record,
            name=next_name,
            prompt=next_prompt,
            blurb=next_blurb,
            status=next_status,
            updated_at=datetime.now(timezone.utc),
        )
        return self._repository.save(updated)

    def delete(self, pack_id: str) -> None:
        record = self.get(pack_id)
        if record.type is SkillPackType.SQL_GENERATE:
            raise Conflict("SQL 生成占位技能包不可删除")
        self._repository.delete(pack_id)


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not 1 <= len(clean) <= 160:
        raise ValidationFailed("name must contain between 1 and 160 characters")
    return clean
