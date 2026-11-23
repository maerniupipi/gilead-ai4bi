"""Pick the analysis grid the same way export_xlsx does."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xiaoying_quick.application.agent_run.tools import snapshot_query_table


def select_analysis_table(tables: Sequence[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """Prefer the largest verified grid, not a later 1-row probe."""

    snapshots: list[dict[str, Any]] = []
    for item in tables or ():
        if not isinstance(item, Mapping):
            continue
        snapshot = snapshot_query_table(item, question=str(item.get("question") or ""))
        if snapshot is not None:
            snapshots.append(snapshot)
    if not snapshots:
        return None
    return max(
        enumerate(snapshots),
        key=lambda pair: (int(pair[1]["row_count"]), pair[0]),
    )[1]
