"""Persistence port owned by the runs module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from xiaoying_quick.modules.runs.contracts import RunEvent, RunRecord, RunStatus
from xiaoying_quick.shared.result import CursorPage


class RunRepository(Protocol):
    def add(self, run: RunRecord) -> RunRecord: ...

    def get(self, run_id: str) -> RunRecord | None: ...

    def find_by_idempotency(self, owner_user_id: str, key: str) -> RunRecord | None: ...

    def list_runs(
        self, *, owner_user_id: str | None, limit: int, offset: int
    ) -> tuple[RunRecord, ...]: ...

    def list_children(self, parent_run_id: str) -> tuple[RunRecord, ...]: ...

    def set_status(
        self, run_id: str, *, expected: RunStatus, target: RunStatus, now: datetime
    ) -> RunRecord: ...

    def update_insight_meta(
        self, run_id: str, *, insight_meta: dict[str, Any], now: datetime
    ) -> RunRecord: ...

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> RunEvent: ...

    def list_events(self, run_id: str, *, after: int, limit: int) -> CursorPage[RunEvent]: ...
