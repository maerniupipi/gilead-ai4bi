"""SQLAlchemy skill pack repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.skill_packs import SkillPackModel
from xiaoying_quick.infrastructure.persistence.session import optional_nested_transaction
from xiaoying_quick.modules.skill_packs.contracts import (
    SkillPackRecord,
    SkillPackStatus,
    SkillPackType,
)
from xiaoying_quick.shared.errors import Conflict, NotFound


class SqlAlchemySkillPackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, pack_id: str) -> SkillPackRecord | None:
        model = self._session.get(SkillPackModel, pack_id)
        return self._to_record(model) if model else None

    def list_all(self) -> tuple[SkillPackRecord, ...]:
        statement = select(SkillPackModel).order_by(SkillPackModel.created_at.asc())
        return tuple(self._to_record(model) for model in self._session.scalars(statement))

    def list_by_type(
        self, pack_type: SkillPackType, *, active_only: bool = False
    ) -> tuple[SkillPackRecord, ...]:
        statement = select(SkillPackModel).where(SkillPackModel.type == pack_type.value)
        if active_only:
            statement = statement.where(SkillPackModel.status == SkillPackStatus.ACTIVE.value)
        statement = statement.order_by(SkillPackModel.created_at.asc())
        return tuple(self._to_record(model) for model in self._session.scalars(statement))

    def add(self, record: SkillPackRecord) -> SkillPackRecord:
        model = SkillPackModel(
            id=record.id,
            name=record.name,
            type=record.type.value,
            prompt=record.prompt,
            blurb=record.blurb,
            status=record.status.value,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        try:
            with optional_nested_transaction(self._session):
                self._session.add(model)
                self._session.flush()
        except IntegrityError as exc:
            raise Conflict("skill pack id already exists") from exc
        return self._to_record(model)

    def save(self, record: SkillPackRecord) -> SkillPackRecord:
        model = self._session.get(SkillPackModel, record.id)
        if model is None:
            raise NotFound("skill pack not found")
        model.name = record.name
        model.type = record.type.value
        model.prompt = record.prompt
        model.blurb = record.blurb
        model.status = record.status.value
        model.created_by = record.created_by
        model.updated_at = record.updated_at
        self._session.flush()
        return self._to_record(model)

    def delete(self, pack_id: str) -> None:
        model = self._session.get(SkillPackModel, pack_id)
        if model is None:
            raise NotFound("skill pack not found")
        self._session.delete(model)
        self._session.flush()

    @staticmethod
    def _to_record(model: SkillPackModel) -> SkillPackRecord:
        return SkillPackRecord(
            id=model.id,
            name=model.name,
            type=SkillPackType(model.type),
            prompt=model.prompt or "",
            blurb=model.blurb or "",
            status=SkillPackStatus(model.status),
            created_by=model.created_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
