"""SQLAlchemy repository for the model registry."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from xiaoying_quick.modules.models.contracts import ModelConfigRecord
from xiaoying_quick.modules.models.ports import ModelConfigRepository

from ..models.model_configs import ModelConfigModel


class SqlAlchemyModelConfigRepository(ModelConfigRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: ModelConfigRecord) -> ModelConfigRecord:
        model = _to_model(record)
        self._session.add(model)
        self._session.flush()
        return _to_record(model)

    def get(self, config_id: str) -> ModelConfigRecord | None:
        model = self._session.get(ModelConfigModel, config_id)
        return _to_record(model) if model is not None else None

    def get_by_name(self, name: str) -> ModelConfigRecord | None:
        model = self._session.scalar(select(ModelConfigModel).where(ModelConfigModel.name == name))
        return _to_record(model) if model is not None else None

    def list_all(self) -> tuple[ModelConfigRecord, ...]:
        rows = self._session.scalars(
            select(ModelConfigModel).order_by(ModelConfigModel.created_at)
        ).all()
        return tuple(_to_record(row) for row in rows)

    def active(self) -> ModelConfigRecord | None:
        model = self._session.scalar(
            select(ModelConfigModel).where(ModelConfigModel.is_active.is_(True)).limit(1)
        )
        return _to_record(model) if model is not None else None

    def save(self, record: ModelConfigRecord) -> ModelConfigRecord:
        model = self._session.get(ModelConfigModel, record.id)
        if model is None:
            raise LookupError(f"model config {record.id} disappeared")
        model.name = record.name
        model.endpoint_url = record.endpoint_url
        model.model_id = record.model_id
        model.secret_ref = record.secret_ref
        model.temperature = record.temperature
        model.max_tokens = record.max_tokens
        model.reasoning = record.reasoning
        model.timeout_seconds = record.timeout_seconds
        model.is_active = record.is_active
        self._session.flush()
        return _to_record(model)

    def delete(self, config_id: str) -> None:
        model = self._session.get(ModelConfigModel, config_id)
        if model is not None:
            self._session.delete(model)
            self._session.flush()

    def clear_active(self) -> None:
        self._session.execute(
            update(ModelConfigModel)
            .where(ModelConfigModel.is_active.is_(True))
            .values(is_active=False)
        )
        self._session.flush()


def _to_model(record: ModelConfigRecord) -> ModelConfigModel:
    return ModelConfigModel(
        id=record.id,
        name=record.name,
        endpoint_url=record.endpoint_url,
        model_id=record.model_id,
        secret_ref=record.secret_ref,
        temperature=record.temperature,
        max_tokens=record.max_tokens,
        reasoning=record.reasoning,
        timeout_seconds=record.timeout_seconds,
        is_active=record.is_active,
    )


def _to_record(model: ModelConfigModel) -> ModelConfigRecord:
    return ModelConfigRecord(
        id=model.id,
        name=model.name,
        endpoint_url=model.endpoint_url,
        model_id=model.model_id,
        secret_ref=model.secret_ref,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        reasoning=model.reasoning,
        timeout_seconds=model.timeout_seconds,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
