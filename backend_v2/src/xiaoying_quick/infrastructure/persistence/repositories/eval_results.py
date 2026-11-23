"""SQLAlchemy persistence for eval batches and per-item results."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.eval_results import (
    EvalBatchModel,
    EvalResultModel,
)
from xiaoying_quick.shared.clock import SystemClock
from xiaoying_quick.shared.ids import new_id


def _preview(text: str, limit: int = 120) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit]}…"


class SqlAlchemyEvalResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._clock = SystemClock()

    def create_batch(self, *, owner_user_id: str, filename: str) -> EvalBatchModel:
        row = EvalBatchModel(
            id=new_id("evalb"),
            owner_user_id=owner_user_id,
            filename=filename[:200],
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_batch(self, batch_id: str, *, owner_user_id: str) -> EvalBatchModel | None:
        row = self._session.get(EvalBatchModel, batch_id)
        if row is None or row.owner_user_id != owner_user_id:
            return None
        return row

    def upsert_result(
        self,
        *,
        batch_id: str,
        sheet: str,
        row_number: int,
        question: str,
        category: str,
        status: str,
        clarify: str,
        sql_text: str,
        labs: str,
        answer: str,
        duration: str,
        run_id: str,
        error: str,
        headers: list[str],
        extra_values: dict[str, Any],
    ) -> EvalResultModel:
        existing = self._session.scalar(
            select(EvalResultModel).where(
                EvalResultModel.batch_id == batch_id,
                EvalResultModel.sheet == sheet,
                EvalResultModel.row_number == row_number,
            )
        )
        preview = _preview(answer or error)
        now = self._clock.now()
        if existing is None:
            existing = EvalResultModel(
                id=new_id("evali"),
                batch_id=batch_id,
                sheet=sheet,
                row_number=row_number,
                question=question,
                category=category,
                status=status,
                clarify=clarify,
                sql_text=sql_text,
                labs=labs,
                answer=answer,
                duration=duration,
                run_id=run_id,
                error=error,
                answer_preview=preview,
                headers=list(headers),
                extra_values=dict(extra_values),
            )
            self._session.add(existing)
        else:
            existing.question = question
            existing.category = category
            existing.status = status
            existing.clarify = clarify
            existing.sql_text = sql_text
            existing.labs = labs
            existing.answer = answer
            existing.duration = duration
            existing.run_id = run_id
            existing.error = error
            existing.answer_preview = preview
            existing.headers = list(headers)
            existing.extra_values = dict(extra_values)
            existing.updated_at = now
        self._session.flush()
        return existing

    def list_summaries(self, batch_id: str) -> list[EvalResultModel]:
        return list(
            self._session.scalars(
                select(EvalResultModel)
                .where(EvalResultModel.batch_id == batch_id)
                .order_by(EvalResultModel.sheet, EvalResultModel.row_number)
            ).all()
        )

    def get_result(
        self, batch_id: str, *, sheet: str, row_number: int
    ) -> EvalResultModel | None:
        return self._session.scalar(
            select(EvalResultModel).where(
                EvalResultModel.batch_id == batch_id,
                EvalResultModel.sheet == sheet,
                EvalResultModel.row_number == row_number,
            )
        )
