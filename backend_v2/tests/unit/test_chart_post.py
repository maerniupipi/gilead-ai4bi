"""Post-loop chart select / judge parse / ECharts build."""

from __future__ import annotations

import asyncio
from typing import Any

from xiaoying_quick.application.agent_run.chart_post import maybe_build_charts
from xiaoying_quick.application.charts.builder import build_chart_payload
from xiaoying_quick.application.charts.judge import parse_judge_payload
from xiaoying_quick.application.charts.select import select_analysis_table
from xiaoying_quick.modules.agent.events import AgentEventType, validate_agent_event


def test_select_analysis_table_prefers_largest_grid() -> None:
    tables = [
        {
            "columns": ["区域", "销量"],
            "rows": [["东", 10], ["西", 20], ["南", 30]],
            "sql": "select big",
            "truncated": False,
        },
        {
            "columns": ["最新月"],
            "rows": [["202608"]],
            "sql": "select probe",
            "truncated": False,
        },
    ]
    chosen = select_analysis_table(tables)
    assert chosen is not None
    assert chosen["row_count"] == 3
    assert chosen["sql"].startswith("select big")


def test_parse_judge_unsuitable_is_silent_shape() -> None:
    judged = parse_judge_payload({"suitable": False, "reason": "元数据问题", "charts": []})
    assert judged == {"suitable": False, "reason": "元数据问题", "charts": []}


def test_parse_judge_pads_common_charts_to_three() -> None:
    judged = parse_judge_payload(
        {
            "suitable": True,
            "reason": "区域对比",
            "charts": [
                {
                    "type": "bar",
                    "title": "销量",
                    "mapping": {"x": "区域", "y": "销量"},
                }
            ],
            "data": {"columns": ["区域", "销量"]},
        }
    )
    assert judged is not None
    assert judged["suitable"] is True
    assert len(judged["charts"]) == 3
    assert judged["charts"][0]["type"] == "bar"
    assert {item["type"] for item in judged["charts"]} <= {
        "bar",
        "line",
        "pie",
        "progress",
        "heatmap",
        "scatter",
        "area",
        "radar",
        "funnel",
        "stacked_bar",
    }


def test_build_chart_payload_emits_three_options() -> None:
    table = {
        "columns": ["区域", "销量"],
        "rows": [["东区", 100], ["西区", 80], ["南区", 60], ["北区", 40]],
        "sql": "select 1",
        "row_count": 4,
        "truncated": False,
    }
    judged = {
        "suitable": True,
        "reason": "对比",
        "charts": [
            {"type": "bar", "title": "柱", "mapping": {"x": "区域", "y": "销量"}, "style": {}},
            {"type": "line", "title": "线", "mapping": {"x": "区域", "y": "销量"}, "style": {}},
            {"type": "pie", "title": "饼", "mapping": {"x": "区域", "y": "销量"}, "style": {}},
        ],
    }
    payload = build_chart_payload(judged=judged, table=table)
    assert payload is not None
    assert payload["default_type"] == "bar"
    assert len(payload["charts"]) == 3
    assert payload["charts"][0]["option"]["series"][0]["type"] == "bar"
    validate_agent_event(AgentEventType.CHART_READY, payload)


def test_build_chart_payload_skips_when_unsuitable() -> None:
    assert (
        build_chart_payload(
            judged={"suitable": False, "charts": []},
            table={"columns": ["a"], "rows": [[1]]},
        )
        is None
    )


class _FakeClient:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload

    async def complete_json(self, **kwargs: Any) -> Any:
        del kwargs

        class _Completion:
            def __init__(self, body: dict[str, Any] | None) -> None:
                self.payload = body

        return _Completion(self.payload)


def test_maybe_build_charts_silent_without_tables() -> None:
    result = asyncio.run(
        maybe_build_charts(
            client=_FakeClient({"suitable": True}),
            question="q",
            answer="a",
            query_tables=[],
        )
    )
    assert result is None


def test_maybe_build_charts_silent_when_judge_rejects() -> None:
    tables = [
        {
            "columns": ["最新月"],
            "rows": [["202608"]],
            "sql": "select max(month)",
            "truncated": False,
        }
    ]
    result = asyncio.run(
        maybe_build_charts(
            client=_FakeClient({"suitable": False, "reason": "单点时间", "charts": []}),
            question="最新数据时间是什么？",
            answer="最新月是 202608。",
            query_tables=tables,
        )
    )
    assert result is None


def test_maybe_build_charts_falls_back_when_judge_rejects_chartable_grid() -> None:
    tables = [
        {
            "columns": ["区域", "销量"],
            "rows": [["东", 1], ["西", 2], ["南", 3], ["北", 4]],
            "sql": "select region, qty",
            "truncated": False,
        }
    ]
    result = asyncio.run(
        maybe_build_charts(
            client=_FakeClient({"suitable": False, "reason": "模型误判", "charts": []}),
            question="各省份的销量是多少？",
            answer="江苏最高。",
            query_tables=tables,
        )
    )
    assert result is not None
    assert len(result["charts"]) == 3
    assert result["default_type"] == "bar"


def test_maybe_build_charts_returns_payload_when_suitable() -> None:
    tables = [
        {
            "columns": ["区域", "销量"],
            "rows": [["东", 1], ["西", 2], ["南", 3]],
            "sql": "select region, qty",
            "truncated": False,
        }
    ]
    judge = {
        "suitable": True,
        "reason": "区域销量",
        "charts": [
            {"type": "bar", "title": "柱", "mapping": {"x": "区域", "y": "销量"}},
            {"type": "line", "title": "线", "mapping": {"x": "区域", "y": "销量"}},
            {"type": "pie", "title": "饼", "mapping": {"x": "区域", "y": "销量"}},
        ],
    }
    result = asyncio.run(
        maybe_build_charts(
            client=_FakeClient(judge),
            question="各大区销量？",
            answer="东 1 西 2 南 3",
            query_tables=tables,
        )
    )
    assert result is not None
    assert len(result["charts"]) == 3
    assert result["default_type"] == "bar"
