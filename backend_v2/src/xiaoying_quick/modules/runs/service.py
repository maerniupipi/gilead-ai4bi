"""Run use cases and ownership checks."""

from __future__ import annotations

import json
from typing import Any

from xiaoying_quick.modules.identity import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.runs.contracts import (
    CreateRunResult,
    RunEvent,
    RunMode,
    RunRecord,
    RunStatus,
)
from xiaoying_quick.modules.runs.ports import RunRepository
from xiaoying_quick.modules.runs.state_machine import validate_transition
from xiaoying_quick.shared.clock import Clock, SystemClock
from xiaoying_quick.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id
from xiaoying_quick.shared.result import CursorPage


class RunService:
    def __init__(self, repository: RunRepository, *, clock: Clock | None = None) -> None:
        self._repository = repository
        self._clock = clock or SystemClock()

    def create_run(
        self,
        *,
        principal: AuthenticatedPrincipal,
        question: str,
        session_id: str | None,
        idempotency_key: str | None,
        mode: RunMode | str = RunMode.NORMAL,
        parent_run_id: str | None = None,
        insight_meta: dict[str, Any] | None = None,
    ) -> CreateRunResult:
        clean_question = question.strip()
        if not 1 <= len(clean_question) <= 10_000:
            raise ValidationFailed("question must contain between 1 and 10000 characters")
        clean_session_id = self._clean_optional_id(session_id, "session_id", max_length=128)
        clean_key = self._clean_optional_id(idempotency_key, "Idempotency-Key", max_length=128)
        run_mode = mode if isinstance(mode, RunMode) else RunMode(str(mode))
        clean_parent = self._clean_optional_id(parent_run_id, "parent_run_id", max_length=64)
        meta = dict(insight_meta or {})

        if clean_parent:
            parent = self._repository.get(clean_parent)
            if parent is None:
                raise NotFound("parent run not found")
            if parent.owner_user_id != principal.user_id and principal.role is not Role.ADMIN:
                raise Forbidden("parent run belongs to another user")
            # Child loops always use the normal agent path.
            run_mode = RunMode.NORMAL

        if clean_key:
            existing = self._repository.find_by_idempotency(principal.user_id, clean_key)
            if existing:
                if existing.question != clean_question or existing.session_id != clean_session_id:
                    raise Conflict("Idempotency-Key was already used with a different request")
                return CreateRunResult(run=existing, created=False)

        now = self._clock.now()
        run = RunRecord(
            id=new_id("run"),
            owner_user_id=principal.user_id,
            session_id=clean_session_id,
            question=clean_question,
            status=RunStatus.RECEIVED,
            idempotency_key=clean_key,
            next_event_cursor=0,
            version=1,
            created_at=now,
            updated_at=now,
            mode=run_mode,
            parent_run_id=clean_parent,
            insight_meta=meta,
        )
        try:
            self._repository.add(run)
        except Conflict:
            concurrent = (
                self._repository.find_by_idempotency(principal.user_id, clean_key)
                if clean_key
                else None
            )
            if (
                concurrent
                and concurrent.question == clean_question
                and concurrent.session_id == clean_session_id
            ):
                return CreateRunResult(run=concurrent, created=False)
            raise
        created_payload: dict[str, Any] = {
            "status": run.status.value,
            "session_id": run.session_id,
        }
        # Keep the normal-mode event shape unchanged; only annotate insight trees.
        if run.mode is not RunMode.NORMAL or run.parent_run_id:
            created_payload["mode"] = run.mode.value
            created_payload["parent_run_id"] = run.parent_run_id
        self._repository.append_event(
            run.id,
            event_type="run.created",
            payload=created_payload,
            now=now,
        )
        created = self._repository.get(run.id)
        if created is None:
            raise RuntimeError("run repository did not persist the new run")
        return CreateRunResult(run=created, created=True)

    def get_run(self, *, principal: AuthenticatedPrincipal, run_id: str) -> RunRecord:
        run = self._repository.get(run_id)
        if run is None:
            raise NotFound("run not found")
        self._authorize(principal, run)
        return run

    def is_cancelled(self, run_id: str) -> bool:
        """Cheap cancellation poll for in-flight workers (no auth)."""

        run = self._repository.get(run_id)
        return run is not None and run.status is RunStatus.CANCELLED

    def cancel_run(self, *, principal: AuthenticatedPrincipal, run_id: str) -> RunRecord:
        """Mark a non-terminal run cancelled; cascade to non-terminal children."""

        run = self.get_run(principal=principal, run_id=run_id)
        if run.status is RunStatus.CANCELLED:
            return run
        if run.status.is_terminal:
            raise Conflict(f"run is already {run.status.value}")
        updated = self.transition(run_id=run_id, target=RunStatus.CANCELLED)
        for child in self._repository.list_children(run_id):
            if child.status.is_terminal:
                continue
            try:
                self.transition(run_id=child.id, target=RunStatus.CANCELLED)
            except Conflict:
                continue
        return updated

    def list_child_runs(
        self, *, principal: AuthenticatedPrincipal, parent_run_id: str
    ) -> tuple[RunRecord, ...]:
        self.get_run(principal=principal, run_id=parent_run_id)
        return self._repository.list_children(parent_run_id)

    def update_insight_meta(self, *, run_id: str, insight_meta: dict[str, Any]) -> RunRecord:
        now = self._clock.now()
        return self._repository.update_insight_meta(
            run_id, insight_meta=insight_meta, now=now
        )

    def peek_final_answer(self, run_id: str) -> str:
        """Best-effort final answer from agent.done events (no auth)."""

        page = self._repository.list_events(run_id, after=0, limit=2000)
        answer = ""
        for event in page.items:
            if event.event_type == "agent.done":
                answer = str(event.payload.get("answer") or answer)
        return answer.strip()

    def peek_chart_ready(self, run_id: str) -> dict[str, Any] | None:
        """Best-effort chart.ready payload from a child run (no auth)."""

        page = self._repository.list_events(run_id, after=0, limit=2000)
        latest: dict[str, Any] | None = None
        for event in page.items:
            if event.event_type == "chart.ready" and isinstance(event.payload, dict):
                latest = dict(event.payload)
        return latest

    def find_idempotent(
        self,
        *,
        principal: AuthenticatedPrincipal,
        idempotency_key: str | None,
    ) -> RunRecord | None:
        clean_key = self._clean_optional_id(
            idempotency_key,
            "Idempotency-Key",
            max_length=128,
        )
        if clean_key is None:
            return None
        return self._repository.find_by_idempotency(principal.user_id, clean_key)

    def list_runs(
        self, *, principal: AuthenticatedPrincipal, limit: int, offset: int
    ) -> tuple[RunRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValidationFailed("limit must be between 1 and 100")
        if offset < 0:
            raise ValidationFailed("offset cannot be negative")
        owner = None if principal.role is Role.ADMIN else principal.user_id
        return self._repository.list_runs(owner_user_id=owner, limit=limit, offset=offset)

    def list_events(
        self,
        *,
        principal: AuthenticatedPrincipal,
        run_id: str,
        after: int,
        limit: int,
    ) -> CursorPage[RunEvent]:
        self.get_run(principal=principal, run_id=run_id)
        if after < 0:
            raise ValidationFailed("event cursor cannot be negative")
        if not 1 <= limit <= 1000:
            raise ValidationFailed("event limit must be between 1 and 1000")
        return self._repository.list_events(run_id, after=after, limit=limit)

    def transition(
        self,
        *,
        run_id: str,
        target: RunStatus,
        event_payload: dict[str, Any] | None = None,
    ) -> RunRecord:
        run = self._repository.get(run_id)
        if run is None:
            raise NotFound("run not found")
        validate_transition(run.status, target)
        payload = {"from": run.status.value, "to": target.value, **(event_payload or {})}
        self._validate_event("run.status_changed", payload)
        now = self._clock.now()
        updated = self._repository.set_status(run_id, expected=run.status, target=target, now=now)
        self._repository.append_event(
            run_id, event_type="run.status_changed", payload=payload, now=now
        )
        refreshed = self._repository.get(updated.id)
        if refreshed is None:
            raise RuntimeError("run disappeared after status transition")
        return refreshed

    def append_event(self, *, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEvent:
        self._validate_event(event_type, payload)
        run = self._repository.get(run_id)
        if run is None:
            raise NotFound("run not found")
        return self._repository.append_event(
            run_id, event_type=event_type, payload=payload, now=self._clock.now()
        )

    @staticmethod
    def _clean_optional_id(value: str | None, field: str, *, max_length: int) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if len(clean) > max_length or any(ord(character) < 32 for character in clean):
            raise ValidationFailed(f"{field} is invalid")
        return clean

    @staticmethod
    def _validate_event(event_type: str, payload: dict[str, Any]) -> None:
        if not 1 <= len(event_type) <= 96 or any(character.isspace() for character in event_type):
            raise ValidationFailed("event_type is invalid")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValidationFailed("event payload must be JSON serializable") from exc
        rich_chart = event_type == "chart.ready" and payload.get("version") == 2
        limit = 4 * 1024 * 1024 if rich_chart else 64 * 1024
        if len(encoded.encode("utf-8")) > limit:
            raise ValidationFailed(
                "analysis chart payload exceeds 4 MiB"
                if rich_chart else "event payload exceeds 64 KiB"
            )

    @staticmethod
    def _authorize(principal: AuthenticatedPrincipal, run: RunRecord) -> None:
        if principal.role is not Role.ADMIN and run.owner_user_id != principal.user_id:
            raise Forbidden("run belongs to another user")
