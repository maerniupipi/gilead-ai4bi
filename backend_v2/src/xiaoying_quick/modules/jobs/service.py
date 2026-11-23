"""Durable job enqueueing, leases, retries, and recovery policy."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from xiaoying_quick.shared.clock import Clock, SystemClock
from xiaoying_quick.shared.errors import Conflict, ValidationFailed

from .contracts import JobKind, JobRecord, JobStatus
from .ports import JobRepository


class JobService:
    def __init__(
        self,
        repository: JobRepository,
        id_factory: Callable[[], str],
        *,
        clock: Clock | None = None,
        lease_seconds: int = 180,
        retry_delay_seconds: int = 2,
    ) -> None:
        if lease_seconds < 30:
            raise ValueError("job lease must be at least 30 seconds")
        if retry_delay_seconds < 0:
            raise ValueError("job retry delay cannot be negative")
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock or SystemClock()
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    def enqueue_start(
        self,
        *,
        run_id: str,
        owner_user_id: str,
        session_id: str,
        question: str,
        model_options: dict[str, str] | None = None,
    ) -> JobRecord:
        payload: dict[str, object] = {"session_id": session_id, "question": question}
        if model_options:
            payload["model_options"] = dict(model_options)
        return self._enqueue(
            run_id=run_id,
            owner_user_id=owner_user_id,
            kind=JobKind.START_QUICK_RUN,
            deduplication_key=f"quick:start:{run_id}",
            payload=payload,
        )

    def enqueue_resume(
        self,
        *,
        run_id: str,
        owner_user_id: str,
        session_id: str,
        case_id: str,
        answer: str,
        answers: tuple[dict[str, str], ...] = (),
        model_options: dict[str, str] | None = None,
    ) -> JobRecord:
        payload: dict[str, object] = {
            "session_id": session_id,
            "answer": answer,
            "case_id": case_id,
        }
        if answers:
            payload["answers"] = list(answers)
        if model_options:
            payload["model_options"] = dict(model_options)
        return self._enqueue(
            run_id=run_id,
            owner_user_id=owner_user_id,
            kind=JobKind.RESUME_QUICK_RUN,
            deduplication_key=f"quick:resume:{case_id}",
            payload=payload,
        )

    def ready(self, *, limit: int = 16) -> tuple[JobRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValidationFailed("job batch limit must be between 1 and 100")
        return self._repository.list_ready(now=self._clock.now(), limit=limit)

    def claim(self, job_id: str, *, worker_id: str) -> JobRecord | None:
        clean_worker = self._required(worker_id, "worker_id", max_length=128)
        now = self._clock.now()
        return self._repository.claim(
            self._required(job_id, "job_id", max_length=64),
            worker_id=clean_worker,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )

    def renew(self, job_id: str, *, worker_id: str) -> bool:
        now = self._clock.now()
        return self._repository.renew_lease(
            job_id,
            worker_id=worker_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )

    def succeed(self, job_id: str, *, worker_id: str) -> JobRecord | None:
        return self._repository.mark_succeeded(
            job_id,
            worker_id=worker_id,
            now=self._clock.now(),
        )

    def fail(
        self,
        job: JobRecord,
        *,
        worker_id: str,
        error_code: str,
        terminal: bool = False,
    ) -> JobRecord | None:
        now = self._clock.now()
        terminal = terminal or job.attempt_count >= job.max_attempts
        delay = self._retry_delay_seconds * max(1, job.attempt_count)
        return self._repository.release_after_failure(
            job.id,
            worker_id=worker_id,
            now=now,
            available_at=now + timedelta(seconds=delay),
            error_code=self._required(error_code, "error_code", max_length=96),
            terminal=terminal,
        )

    def recover_stale(self) -> int:
        return self._repository.requeue_stale(now=self._clock.now())

    def _enqueue(
        self,
        *,
        run_id: str,
        owner_user_id: str,
        kind: JobKind,
        deduplication_key: str,
        payload: dict[str, Any],
    ) -> JobRecord:
        clean_run = self._required(run_id, "run_id", max_length=64)
        clean_owner = self._required(owner_user_id, "owner_user_id", max_length=64)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValidationFailed("job payload exceeds 256 KiB")
        existing = self._repository.find_by_deduplication_key(deduplication_key)
        if existing is not None:
            if (
                existing.run_id != clean_run
                or existing.owner_user_id != clean_owner
                or existing.kind is not kind
                or existing.payload != payload
            ):
                raise Conflict("job deduplication key belongs to another payload")
            return existing
        now = self._clock.now()
        record = JobRecord(
            id=self._id_factory(),
            run_id=clean_run,
            owner_user_id=clean_owner,
            kind=kind,
            deduplication_key=deduplication_key,
            payload=dict(payload),
            status=JobStatus.PENDING,
            attempt_count=0,
            max_attempts=3,
            available_at=now,
            locked_by=None,
            lease_expires_at=None,
            last_error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        try:
            return self._repository.add(record)
        except Conflict:
            concurrent = self._repository.find_by_deduplication_key(deduplication_key)
            if (
                concurrent is not None
                and concurrent.run_id == clean_run
                and concurrent.owner_user_id == clean_owner
                and concurrent.kind is kind
                and concurrent.payload == payload
            ):
                return concurrent
            raise

    @staticmethod
    def _required(value: str, field: str, *, max_length: int) -> str:
        clean = value.strip()
        if not clean or len(clean) > max_length or any(ord(character) < 32 for character in clean):
            raise ValidationFailed(f"{field} is invalid")
        return clean
