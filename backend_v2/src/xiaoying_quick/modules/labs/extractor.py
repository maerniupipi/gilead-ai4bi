"""Fail-closed projection of an untrusted Lab response."""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import (
    CandidateSQL,
    LabContractError,
    LabContractErrorCode,
)


class LabResponseExtractor:
    """Extract SQL citations, plus optional display-only Lab narrative.

    Returned rows, numbers and data citations stay discarded. ``narrative`` is
    the Lab's 理解/步骤/总结 text for the run trace, never a Fact.
    """

    def extract(
        self,
        response: object,
        *,
        atom_id: str,
        lab_id: str,
    ) -> tuple[CandidateSQL, ...]:
        if not isinstance(response, Mapping):
            raise LabContractError(
                LabContractErrorCode.INVALID_RESPONSE,
                "Lab response must be an object",
            )
        if "sql_citations" not in response:
            raise LabContractError(
                LabContractErrorCode.MISSING_SQL_CITATIONS,
                "Lab response does not contain top-level sql_citations",
            )

        citations = response["sql_citations"]
        if not isinstance(citations, list):
            raise LabContractError(
                LabContractErrorCode.INVALID_SQL_CITATIONS,
                "sql_citations must be an array",
            )
        raw_narrative = response.get("narrative")
        narrative = raw_narrative.strip() if isinstance(raw_narrative, str) else ""
        raw_session_id = response.get("lab_session_id")
        session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""

        candidates: list[CandidateSQL] = []
        for index, citation in enumerate(citations):
            if not isinstance(citation, Mapping):
                continue
            query = citation.get("query")
            sql = citation.get("sql")
            if not isinstance(query, str) or not query.strip():
                continue
            if not isinstance(sql, str) or not sql.strip():
                continue
            candidates.append(
                CandidateSQL(
                    atom_id=atom_id,
                    lab_id=lab_id,
                    query=query,
                    sql=sql,
                    candidate_no=index,
                    narrative=narrative,
                    session_id=session_id,
                )
            )

        if not candidates:
            raise LabContractError(
                LabContractErrorCode.NO_VALID_SQL_CITATIONS,
                "Lab response contains no valid query/sql citation pairs",
            )
        return tuple(candidates)
