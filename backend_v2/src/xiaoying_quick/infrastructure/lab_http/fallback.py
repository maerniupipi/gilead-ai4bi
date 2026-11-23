"""Non-production laboratory fallback that still speaks the SQL-citation contract."""

from __future__ import annotations

from typing import Any

from xiaoying_quick.modules.labs import CandidateSQL, LabRequest, LabResponseExtractor


def classify_lab_failure(exc: BaseException) -> str:
    name = type(exc).__name__.casefold()
    text = str(exc).casefold()
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if "unavailable" in name or "unavailable" in text:
        return "unconfigured"
    if "network" in name or "connect" in text:
        return "network"
    if "contract" in name or "citation" in text:
        return "contract"
    if "http" in name or "status" in text:
        return "http"
    return "error"


def mock_lab_payload(request: LabRequest) -> dict[str, Any]:
    """Extractor-shaped body: top-level sql_citations, query equals the atom."""

    sql = f"SELECT 1 AS value /* fallback lab_id={request.lab_id} atom={request.atom_id} */"
    return {
        "sql_citations": [
            {
                "query": request.query,
                "sql": sql,
            }
        ]
    }


class FallbackLabPort:
    """Try the real lab first; on failure return extractor-valid citations."""

    supports_controlled_prompt = False

    def __init__(self, inner: object | None, *, on_error: bool = True) -> None:
        self._inner = inner
        self._on_error = on_error
        self._extractor = LabResponseExtractor()
        self.last_fallback: dict[str, object] | None = None

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        self.last_fallback = None
        if self._inner is not None:
            try:
                return await self._inner.generate_sql(request)  # type: ignore[no-any-return]
            except Exception as exc:
                if not self._on_error:
                    raise
                reason = classify_lab_failure(exc)
        else:
            reason = "unconfigured"
        payload = mock_lab_payload(request)
        candidates = self._extractor.extract(
            payload, atom_id=request.atom_id, lab_id=request.lab_id
        )
        self.last_fallback = {
            "reason": reason,
            "fallback": True,
            "atom_id": request.atom_id,
            "lab_id": request.lab_id,
            "query": request.query,
        }
        return candidates
