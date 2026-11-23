"""Public run contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from xiaoying_quick.shared.compat import StrEnum


class RunStatus(StrEnum):
    RECEIVED = "received"
    RUNNING = "running"
    WAITING_CLARIFICATION = "waiting_clarification"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.PARTIAL,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


class RunMode(StrEnum):
    NORMAL = "normal"
    INSIGHT = "insight"


@dataclass(frozen=True)
class RunRecord:
    id: str
    owner_user_id: str
    session_id: str | None
    question: str
    status: RunStatus
    idempotency_key: str | None
    next_event_cursor: int
    version: int
    created_at: datetime
    updated_at: datetime
    mode: RunMode = RunMode.NORMAL
    parent_run_id: str | None = None
    insight_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    cursor: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class CreateRunResult:
    run: RunRecord
    created: bool
