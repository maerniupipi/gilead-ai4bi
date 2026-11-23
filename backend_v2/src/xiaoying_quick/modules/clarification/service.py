from __future__ import annotations

from xiaoying_quick.modules.identity import AuthenticatedPrincipal
from xiaoying_quick.shared.errors import ValidationFailed

from .contracts import ClarificationCase
from .ports import ClarificationCaseRepository


class ClarificationQueryService:
    """Read pending clarification cases without crossing the current owner boundary."""

    def __init__(self, repository: ClarificationCaseRepository) -> None:
        self._repository = repository

    def list_waiting(
        self,
        *,
        principal: AuthenticatedPrincipal,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[ClarificationCase, ...]:
        return tuple(
            self._repository.list_waiting(
                owner_user_id=principal.user_id,
                run_id=self._clean_filter(run_id, "run_id"),
                session_id=self._clean_filter(session_id, "session_id"),
            )
        )

    @staticmethod
    def _clean_filter(value: str | None, field: str) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean or len(clean) > 64 or any(ord(character) < 32 for character in clean):
            raise ValidationFailed(f"{field} is invalid")
        return clean


__all__ = ["ClarificationQueryService"]
