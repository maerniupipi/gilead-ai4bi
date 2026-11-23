from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from xiaoying_quick.shared.compat import StrEnum


class EvidenceState(StrEnum):
    COMPLETE = "complete"
    EMPTY = "empty"
    TRUNCATED = "truncated"
    FAILED = "failed"


@dataclass(frozen=True)
class DataColumn:
    name: str
    logical_type: str


@dataclass(frozen=True)
class DatasetEvidence:
    id: str
    run_id: str
    atom_id: str
    execution_id: str
    approved_sql_id: str
    sql_fingerprint: str
    data_source_revision_id: str
    state: EvidenceState
    columns: tuple[DataColumn, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool
    result_hash: str
    duration_ms: int
    executed_at: datetime


@dataclass(frozen=True)
class ExecutionGap:
    atom_id: str
    code: str
    message: str
    retryable: bool = False
