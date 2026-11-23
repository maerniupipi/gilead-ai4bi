"""SQLAlchemy implementation of the run repository port."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.runs import RunEventModel, RunModel
from xiaoying_quick.infrastructure.persistence.session import optional_nested_transaction
from xiaoying_quick.modules.runs.contracts import RunEvent, RunMode, RunRecord, RunStatus
from xiaoying_quick.shared.errors import Conflict, NotFound
from xiaoying_quick.shared.result import CursorPage


class SqlAlchemyRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: RunRecord) -> RunRecord:
        model = RunModel(
            id=run.id,
            owner_user_id=run.owner_user_id,
            session_id=run.session_id,
            question=run.question,
            status=run.status.value,
            mode=run.mode.value,
            parent_run_id=run.parent_run_id,
            insight_meta=dict(run.insight_meta or {}),
            idempotency_key=run.idempotency_key,
            next_event_cursor=run.next_event_cursor,
            version=run.version,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
        try:
            with optional_nested_transaction(self._session):
                self._session.add(model)
                self._session.flush()
        except IntegrityError as exc:
            raise Conflict("run id or Idempotency-Key already exists") from exc
        return self._to_record(model)

    def get(self, run_id: str) -> RunRecord | None:
        model = self._session.get(RunModel, run_id)
        return self._to_record(model) if model else None

    def find_by_idempotency(self, owner_user_id: str, key: str) -> RunRecord | None:
        model = self._session.scalar(
            select(RunModel).where(
                RunModel.owner_user_id == owner_user_id,
                RunModel.idempotency_key == key,
            )
        )
        return self._to_record(model) if model else None

    def list_runs(
        self, *, owner_user_id: str | None, limit: int, offset: int
    ) -> tuple[RunRecord, ...]:
        statement = select(RunModel)
        if owner_user_id is not None:
            statement = statement.where(RunModel.owner_user_id == owner_user_id)
        statement = statement.order_by(RunModel.created_at.desc()).limit(limit).offset(offset)
        return tuple(self._to_record(model) for model in self._session.scalars(statement))

    def list_children(self, parent_run_id: str) -> tuple[RunRecord, ...]:
        statement = (
            select(RunModel)
            .where(RunModel.parent_run_id == parent_run_id)
            .order_by(RunModel.created_at.asc())
        )
        return tuple(self._to_record(model) for model in self._session.scalars(statement))

    def set_status(
        self, run_id: str, *, expected: RunStatus, target: RunStatus, now: datetime
    ) -> RunRecord:
        model = self._session.scalar(
            select(RunModel).where(RunModel.id == run_id).with_for_update()
        )
        if model is None:
            raise NotFound("run not found")
        if model.status != expected.value:
            raise Conflict(
                f"run status changed concurrently: expected {expected.value}, got {model.status}"
            )
        model.status = target.value
        model.version += 1
        model.updated_at = now
        self._session.flush()
        return self._to_record(model)

    def update_insight_meta(
        self, run_id: str, *, insight_meta: dict[str, Any], now: datetime
    ) -> RunRecord:
        model = self._session.scalar(
            select(RunModel).where(RunModel.id == run_id).with_for_update()
        )
        if model is None:
            raise NotFound("run not found")
        model.insight_meta = dict(insight_meta)
        model.version += 1
        model.updated_at = now
        self._session.flush()
        return self._to_record(model)

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> RunEvent:
        run = self._session.scalar(select(RunModel).where(RunModel.id == run_id).with_for_update())
        if run is None:
            raise NotFound("run not found")
        run.next_event_cursor += 1
        run.updated_at = now
        event = RunEventModel(
            run_id=run_id,
            cursor=run.next_event_cursor,
            event_type=event_type,
            payload=dict(payload),
            created_at=now,
        )
        self._session.add(event)
        self._session.flush()
        return self._to_event(event)

    def list_events(self, run_id: str, *, after: int, limit: int) -> CursorPage[RunEvent]:
        statement = (
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id, RunEventModel.cursor > after)
            .order_by(RunEventModel.cursor)
            .limit(limit + 1)
        )
        rows = tuple(self._session.scalars(statement))
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(self._to_event(model) for model in visible)
        next_cursor = items[-1].cursor if items else after
        return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _to_record(model: RunModel) -> RunRecord:
        raw_mode = getattr(model, "mode", None) or RunMode.NORMAL.value
        try:
            mode = RunMode(raw_mode)
        except ValueError:
            mode = RunMode.NORMAL
        meta = getattr(model, "insight_meta", None)
        return RunRecord(
            id=model.id,
            owner_user_id=model.owner_user_id,
            session_id=model.session_id,
            question=model.question,
            status=RunStatus(model.status),
            idempotency_key=model.idempotency_key,
            next_event_cursor=model.next_event_cursor,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
            mode=mode,
            parent_run_id=getattr(model, "parent_run_id", None),
            insight_meta=dict(meta) if isinstance(meta, dict) else {},
        )

    @staticmethod
    def _to_event(model: RunEventModel) -> RunEvent:
        return RunEvent(
            run_id=model.run_id,
            cursor=model.cursor,
            event_type=model.event_type,
            payload=dict(model.payload),
            created_at=model.created_at,
        )
