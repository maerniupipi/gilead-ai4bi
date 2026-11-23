"""SQLAlchemy compare-and-set repository for durable Quick jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast, overload

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.session import optional_nested_transaction
from xiaoying_quick.modules.jobs import JobKind, JobRecord, JobStatus
from xiaoying_quick.shared.errors import Conflict

from ..models.jobs import QuickJobModel


class SqlAlchemyJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: JobRecord) -> JobRecord:
        model = QuickJobModel(
            id=job.id,
            run_id=job.run_id,
            owner_user_id=job.owner_user_id,
            kind=job.kind.value,
            deduplication_key=job.deduplication_key,
            payload=dict(job.payload),
            status=job.status.value,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            available_at=job.available_at,
            locked_by=job.locked_by,
            lease_expires_at=job.lease_expires_at,
            last_error_code=job.last_error_code,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )
        try:
            with optional_nested_transaction(self._session):
                self._session.add(model)
                self._session.flush()
        except IntegrityError as exc:
            raise Conflict("job id or deduplication key already exists") from exc
        return self._record(model)

    def get(self, job_id: str) -> JobRecord | None:
        model = self._session.get(QuickJobModel, job_id)
        return self._record(model) if model is not None else None

    def find_by_deduplication_key(self, key: str) -> JobRecord | None:
        model = self._session.scalar(
            select(QuickJobModel).where(QuickJobModel.deduplication_key == key)
        )
        return self._record(model) if model is not None else None

    def list_ready(self, *, now: datetime, limit: int) -> tuple[JobRecord, ...]:
        models = self._session.scalars(
            select(QuickJobModel)
            .where(
                QuickJobModel.status == JobStatus.PENDING.value,
                QuickJobModel.available_at <= now,
            )
            .order_by(QuickJobModel.available_at, QuickJobModel.created_at, QuickJobModel.id)
            .limit(limit)
        ).all()
        return tuple(self._record(model) for model in models)

    def claim(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> JobRecord | None:
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.id == job_id,
                    QuickJobModel.status == JobStatus.PENDING.value,
                    QuickJobModel.available_at <= now,
                )
                .values(
                    status=JobStatus.RUNNING.value,
                    attempt_count=QuickJobModel.attempt_count + 1,
                    locked_by=worker_id,
                    lease_expires_at=lease_expires_at,
                    updated_at=now,
                    completed_at=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            return None
        self._session.flush()
        return self.get(job_id)

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.id == job_id,
                    QuickJobModel.status == JobStatus.RUNNING.value,
                    QuickJobModel.locked_by == worker_id,
                )
                .values(lease_expires_at=lease_expires_at, updated_at=now)
                .execution_options(synchronize_session=False)
            ),
        )
        return bool(result.rowcount == 1)

    def mark_succeeded(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
    ) -> JobRecord | None:
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.id == job_id,
                    QuickJobModel.status == JobStatus.RUNNING.value,
                    QuickJobModel.locked_by == worker_id,
                )
                .values(
                    status=JobStatus.SUCCEEDED.value,
                    locked_by=None,
                    lease_expires_at=None,
                    updated_at=now,
                    completed_at=now,
                    last_error_code=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            return None
        self._session.flush()
        return self.get(job_id)

    def release_after_failure(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        available_at: datetime,
        error_code: str,
        terminal: bool,
    ) -> JobRecord | None:
        target = JobStatus.FAILED if terminal else JobStatus.PENDING
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.id == job_id,
                    QuickJobModel.status == JobStatus.RUNNING.value,
                    QuickJobModel.locked_by == worker_id,
                )
                .values(
                    status=target.value,
                    available_at=available_at,
                    locked_by=None,
                    lease_expires_at=None,
                    last_error_code=error_code,
                    updated_at=now,
                    completed_at=now if terminal else None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            return None
        self._session.flush()
        return self.get(job_id)

    def requeue_stale(self, *, now: datetime) -> int:
        terminal = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.status == JobStatus.RUNNING.value,
                    QuickJobModel.lease_expires_at.is_not(None),
                    QuickJobModel.lease_expires_at <= now,
                    QuickJobModel.attempt_count >= QuickJobModel.max_attempts,
                )
                .values(
                    status=JobStatus.FAILED.value,
                    locked_by=None,
                    lease_expires_at=None,
                    last_error_code="LEASE_EXPIRED",
                    updated_at=now,
                    completed_at=now,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        recovered = cast(
            CursorResult[Any],
            self._session.execute(
                update(QuickJobModel)
                .where(
                    QuickJobModel.status == JobStatus.RUNNING.value,
                    QuickJobModel.lease_expires_at.is_not(None),
                    QuickJobModel.lease_expires_at <= now,
                    QuickJobModel.attempt_count < QuickJobModel.max_attempts,
                )
                .values(
                    status=JobStatus.PENDING.value,
                    available_at=now,
                    locked_by=None,
                    lease_expires_at=None,
                    last_error_code="LEASE_EXPIRED",
                    updated_at=now,
                    completed_at=None,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return int(terminal.rowcount or 0) + int(recovered.rowcount or 0)

    @staticmethod
    def _record(model: QuickJobModel) -> JobRecord:
        return JobRecord(
            id=model.id,
            run_id=model.run_id,
            owner_user_id=model.owner_user_id,
            kind=JobKind(model.kind),
            deduplication_key=model.deduplication_key,
            payload=dict(model.payload),
            status=JobStatus(model.status),
            attempt_count=model.attempt_count,
            max_attempts=model.max_attempts,
            available_at=_aware(model.available_at),
            locked_by=model.locked_by,
            lease_expires_at=_aware(model.lease_expires_at),
            last_error_code=model.last_error_code,
            created_at=_aware(model.created_at),
            updated_at=_aware(model.updated_at),
            completed_at=_aware(model.completed_at),
        )


@overload
def _aware(value: datetime) -> datetime: ...


@overload
def _aware(value: None) -> None: ...


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
