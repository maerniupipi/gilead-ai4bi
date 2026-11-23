from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contracts import ClarificationCase


class ClarificationCaseRepository(Protocol):
    def get(self, case_id: str) -> ClarificationCase | None: ...

    def for_run(self, run_id: str) -> ClarificationCase | None: ...

    def list_answered_for_session(
        self, session_id: str, *, limit: int = 8, workbook_ids: Sequence[str] | None = None
    ) -> list[ClarificationCase]: ...

    def list_waiting(
        self,
        *,
        owner_user_id: str,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ClarificationCase]: ...

    def save(self, case: ClarificationCase) -> None: ...


__all__ = ["ClarificationCaseRepository"]
