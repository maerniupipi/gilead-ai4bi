from __future__ import annotations

import asyncio

from xiaoying_quick.application.agent_run.tools import (
    build_export_xlsx_tool,
    build_query_db_tool,
)
from xiaoying_quick.modules.agent import AgentToolContext


class _Artifacts:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def append(self, *, run_id: str, kind: str, payload: dict, atom_id: str | None = None) -> str:
        export_id = f"artifact_{len(self.items) + 1}"
        self.items[export_id] = {
            "run_id": run_id,
            "kind": kind,
            "payload": payload,
            "atom_id": atom_id,
        }
        return export_id


def _context(*, tables=None, artifacts=None, query=None) -> AgentToolContext:
    extras: dict = {}
    if tables is not None:
        extras["query_tables"] = tables
    if artifacts is not None:
        extras["artifacts"] = artifacts
    if query is not None:
        extras["query_db"] = query
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras=extras,
    )


def test_query_db_clips_visible_rows_and_points_to_export() -> None:
    rows = [[index, f"城市{index}", index * 10] for index in range(462)]

    def query(sql: str, max_rows: int):
        del sql
        return ["地区经理", "城市", "金额"], rows[:max_rows], False, 12

    result = asyncio.run(
        build_query_db_tool().executor(_context(query=query), {"sql": "SELECT 1"})
    )
    assert result.ok is True
    assert len(result.payload["rows"]) == 462
    assert "仅展示前 30 行，共 462 行" in result.output
    assert "export_xlsx" in result.output
    assert "城市29" in result.output
    assert "城市30" not in result.output


def test_export_xlsx_writes_full_grid_and_ignores_model_rows() -> None:
    artifacts = _Artifacts()
    tables = [
        {
            "columns": ["地区经理", "城市", "金额"],
            "rows": [[f"经理{index}", f"城市{index}", index] for index in range(462)],
            "sql": "SELECT 1",
            "truncated": False,
        }
    ]
    result = asyncio.run(
        build_export_xlsx_tool().executor(
            _context(tables=tables, artifacts=artifacts),
            {
                "title": "泰瑞沙 2025 YTD 地区经理城市销售",
                "summary": "Actual 销售金额，2025 全年",
                "rows": [["伪造", "数据", 1]],
            },
        )
    )
    assert result.ok is True
    assert result.payload["row_count"] == 462
    assert result.payload["filename"] == "泰瑞沙 2025 YTD 地区经理城市销售.xlsx"
    assert result.payload["download_path"] == "/api/v2/runs/run-1/exports/artifact_1"
    assert "artifact_1" in result.output
    stored = artifacts.items["artifact_1"]
    assert stored["kind"] == "xlsx_export"
    assert len(stored["payload"]["rows"]) == 462
    assert stored["payload"]["rows"][0][0] == "经理0"
    assert stored["payload"]["rows"][-1][1] == "城市461"


def test_export_xlsx_prefers_the_largest_grid_over_a_later_probe() -> None:
    artifacts = _Artifacts()
    tables = [
        {
            "columns": ["地区经理", "城市", "金额"],
            "rows": [[f"经理{index}", f"城市{index}", index] for index in range(462)],
            "sql": "SELECT dsm, city, amt",
            "truncated": False,
        },
        {
            "columns": ["brand_code", "brand_name"],
            "rows": [["B909", "Tagrisso"]],
            "sql": "SELECT brand_code, brand_name",
            "truncated": False,
        },
    ]
    result = asyncio.run(
        build_export_xlsx_tool().executor(
            _context(tables=tables, artifacts=artifacts),
            {
                "title": "泰瑞沙 2025 YTD 地区经理城市销售",
                "summary": "Actual 销售金额，共 462 行",
            },
        )
    )
    assert result.ok is True
    assert result.payload["row_count"] == 462
    stored = artifacts.items["artifact_1"]["payload"]
    assert stored["columns"] == ["地区经理", "城市", "金额"]
    assert len(stored["rows"]) == 462
    assert stored["rows"][0][0] == "经理0"


def test_export_xlsx_requires_a_prior_query() -> None:
    result = asyncio.run(
        build_export_xlsx_tool().executor(
            _context(tables=[], artifacts=_Artifacts()),
            {"title": "没有数据"},
        )
    )
    assert result.ok is False
    assert "query_db" in result.output
