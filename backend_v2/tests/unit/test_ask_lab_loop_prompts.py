"""ask_lab ships the loop_prompt slots plus the full features set."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from xiaoying_quick.application.agent_run.tools import build_ask_lab_tool
from xiaoying_quick.modules.agent import AgentToolContext
from xiaoying_quick.modules.labs.contracts import CandidateSQL


def _context(lab: AsyncMock) -> AgentToolContext:
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras={"lab": lab},
    )


def test_ask_lab_packs_and_passes_the_loop_prompt_slots(tmp_path: Path) -> None:
    (tmp_path / "业务知识.md").write_text(
        "## 长短词\n长词=短词\n\n## KPI 指标\n| 金额达成率 | A/T% | 实际/指标 |\n",
        encoding="utf-8",
    )
    labs_dir = tmp_path / "labs"
    labs_dir.mkdir()
    (labs_dir / "actual.md").write_text(
        "lab_id: `actual`\n\n## 何时找我\n查实际销售\n", encoding="utf-8"
    )
    lab = AsyncMock(
        return_value=[
            CandidateSQL(
                atom_id="atom-1",
                lab_id="actual",
                query="安达唐今年销量",
                sql="SELECT 1",
                candidate_no=1,
                session_id="lab-sess-1",
            )
        ]
    )
    lab.generate_sql = lab
    spec = build_ask_lab_tool(("actual",), knowledge_root=tmp_path)

    result = asyncio.run(
        spec.executor(
            _context(lab),
            {"question": "安达唐今年的金额达成率", "lab_id": "actual"},
        )
    )

    assert result.ok
    request = lab.await_args.args[0]
    for index in range(1, 6):
        assert f"loop_prompt_{index}" in request.session_params
    assert "金额达成率" in request.session_params["loop_prompt_4"]
    # Slot 3 is the time anchor; slot 5 is reserved and blank.
    assert "时间基准" in request.session_params["loop_prompt_3"]
    assert request.session_params["loop_prompt_5"] == ""
    # The full features set travels with the call: time anchors default to
    # the previous month when no max sales month is configured.
    assert request.session_params["cur_sales_month"] in {str(m) for m in range(1, 13)}
    assert request.session_params["trty_code"] == "rsd_trty_code = RD_R40016"
    assert request.session_params["long_short_words"] == "None"
    assert result.payload["loop_prompts"] == {
        key: request.session_params[key]
        for key in request.session_params
        if key.startswith("loop_prompt_")
    }
    assert result.payload["lab_session_id"] == "lab-sess-1"


def test_ask_lab_passes_remark_and_configured_anchor(tmp_path: Path) -> None:
    (tmp_path / "业务知识.md").write_text("## 词表\n无\n", encoding="utf-8")
    lab = AsyncMock(
        return_value=[
            CandidateSQL(
                atom_id="atom-1",
                lab_id="actual",
                query="q",
                sql="SELECT 1",
                candidate_no=1,
            )
        ]
    )
    lab.generate_sql = lab
    spec = build_ask_lab_tool(("actual",), knowledge_root=tmp_path, max_sales_month="2026-07")

    result = asyncio.run(
        spec.executor(
            _context(lab),
            {
                "question": "安达唐 YTD 达成率",
                "lab_id": "actual",
                "remark": "机构=中南大学湘雅医院，时间已确认 2025H2",
            },
        )
    )

    assert result.ok
    params = lab.await_args.args[0].session_params
    assert params["cur_sales_year"] == "2026"
    assert params["cur_sales_month"] == "7"
    assert params["max_sales_month"] == "7"
    assert "中南大学湘雅医院" in params["remark"]
    assert "2026 年 YTD 即 1 月到 7 月" in params["loop_prompt_3"]


def test_ask_lab_attach_upstream_packs_last_hop(tmp_path: Path) -> None:
    (tmp_path / "业务知识.md").write_text("## 词表\n无\n", encoding="utf-8")
    lab = AsyncMock(
        return_value=[
            CandidateSQL(
                atom_id="atom-1",
                lab_id="actual",
                query="q",
                sql="SELECT 2",
                candidate_no=1,
            )
        ]
    )
    lab.generate_sql = lab
    spec = build_ask_lab_tool(("actual",), knowledge_root=tmp_path)
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras={
            "lab": lab,
            "upstream_hops": [
                {
                    "question": "销量前50省份",
                    "sql": "SELECT province FROM sales LIMIT 50",
                    "columns": ["province"],
                    "rows": [["浙江"], ["江苏"]],
                    "row_count": 2,
                }
            ],
        },
    )
    result = asyncio.run(
        spec.executor(
            context,
            {
                "question": "这些省份的同比增速",
                "lab_id": "actual",
                "attach_upstream": True,
            },
        )
    )
    assert result.ok
    slot = lab.await_args.args[0].session_params["loop_prompt_5"]
    assert "上游已核验" in slot
    assert "SELECT province FROM sales LIMIT 50" in slot
    assert "浙江" in slot
    assert result.payload["attach_upstream"] is True
    assert "loop_prompt_5" in result.output or "上一跳" in result.output


def test_bootcamp_query_carries_confirmed_filters_in_content(tmp_path: Path) -> None:
    lab = AsyncMock(
        return_value=[
            CandidateSQL(
                atom_id="atom-1",
                lab_id="actual",
                query="q",
                sql="SELECT 1",
                candidate_no=1,
            )
        ]
    )
    lab.generate_sql = lab
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras={"lab": lab, "lab_provider": "bootcamp", "lab_mock_enabled": False},
    )
    result = asyncio.run(
        build_ask_lab_tool(("actual",), knowledge_root=tmp_path).executor(
            context,
            {
                "lab_id": "actual",
                "question": "查询品牌销售",
                "remark": "品牌名称必须为样例品牌A，区域=华南",
            },
        )
    )
    assert result.ok
    request = lab.await_args.args[0]
    assert request.query.startswith("查询品牌销售")
    assert "品牌名称必须为样例品牌A，区域=华南" in request.query
    assert len(request.query) <= 2000


def test_ask_lab_attach_upstream_without_hops_stays_empty(tmp_path: Path) -> None:
    (tmp_path / "业务知识.md").write_text("## 词表\n无\n", encoding="utf-8")
    lab = AsyncMock(
        return_value=[
            CandidateSQL(
                atom_id="atom-1",
                lab_id="actual",
                query="q",
                sql="SELECT 1",
                candidate_no=1,
            )
        ]
    )
    lab.generate_sql = lab
    spec = build_ask_lab_tool(("actual",), knowledge_root=tmp_path)
    result = asyncio.run(
        spec.executor(
            _context(lab),
            {"question": "安达唐销量", "lab_id": "actual", "attach_upstream": True},
        )
    )
    assert result.ok
    assert lab.await_args.args[0].session_params["loop_prompt_5"] == ""
    assert "loop_prompt_5 为空" in result.output
