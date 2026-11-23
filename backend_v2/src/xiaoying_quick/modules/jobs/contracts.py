"""Framework-independent contracts for durable Quick jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from xiaoying_quick.shared.compat import StrEnum


class JobKind(StrEnum):
    START_QUICK_RUN = "start_quick_run"
    RESUME_QUICK_RUN = "resume_quick_run"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {JobStatus.SUCCEEDED, JobStatus.FAILED}


@dataclass(frozen=True)
class JobRecord:
    id: str
    run_id: str
    owner_user_id: str
    kind: JobKind
    deduplication_key: str
    payload: dict[str, Any]
    status: JobStatus
    attempt_count: int
    max_attempts: int
    available_at: datetime
    locked_by: str | None
    lease_expires_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
