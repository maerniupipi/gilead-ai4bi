"""Persistence port owned by the durable jobs module."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import JobRecord


class JobRepository(Protocol):
    def add(self, job: JobRecord) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def find_by_deduplication_key(self, key: str) -> JobRecord | None: ...

    def list_ready(self, *, now: datetime, limit: int) -> tuple[JobRecord, ...]: ...

    def claim(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> JobRecord | None: ...

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    def mark_succeeded(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
    ) -> JobRecord | None: ...

    def release_after_failure(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime,
        available_at: datetime,
        error_code: str,
        terminal: bool,
    ) -> JobRecord | None: ...

    def requeue_stale(self, *, now: datetime) -> int: ...
